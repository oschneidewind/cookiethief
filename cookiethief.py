#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
import configparser
import contextlib
import os
import sys
import tempfile
import sqlite3
import http.cookiejar


class SqliteCookieError(Exception):
    pass


class FirefoxCookieError(SqliteCookieError):
    pass


class SqliteCookieJar(http.cookiejar.FileCookieJar):

    def load(self, filename=None, ignore_discard=False, ignore_expires=False):
        if not filename:
            if self.filename is not None:
                filename = self.filename
            else:
                raise ValueError(http.cookiejar.MISSING_FILENAME_TEXT)

        with contextlib.ExitStack() as stack:
            sql = stack.enter_context(tempfile.NamedTemporaryFile(suffix='.sqlite'))
            fin = stack.enter_context(open(filename, 'rb'))

            # Copy sqlite to tmpfile for avoid sqlite lock issues
            for chunk in iter(fin.read, b''):
                sql.write(chunk)

            sqlite = stack.enter_context(sqlite3.connect(sql.name))
            # get a result as dict
            sqlite.row_factory = sqlite3.Row

            for cdict in self._getfromsql(sqlite):
                try:
                    startisdot = cdict['host'].startswith('.')
                    cookie = http.cookiejar.Cookie(0,
                                                   cdict['name'],
                                                   cdict['value'],
                                                   None, False,
                                                   cdict['host'],
                                                   startisdot,
                                                   startisdot,
                                                   cdict['path'], False,
                                                   cdict['isSecure'],
                                                   cdict['expiry'],
                                                   cdict['expiry'],
                                                   None, None, {})
                    if (ignore_expires and cookie.is_expired) or \
                       (ignore_discard and cookie.discard):
                       continue
                    self.set_cookie(cookie)
                except KeyError:
                    msg = "Coudn't convert db entry {} to cookie".format(cdict)
                    raise SqliteCookieError(msg)

    def _getfromsql(self, sqlite):
        raise NotImplementedError


class FirefoxCookieJar(SqliteCookieJar):

    def _getfromsql(self, sqlite):
        keys = ['host', 'path', 'isSecure', 'expiry', 'name', 'value']
        query = 'select {keys} from moz_cookies'.format(keys=','.join(keys))

        cur = sqlite.cursor()
        cur.execute(query)
        for item in cur.fetchall():
            yield item

    @staticmethod
    def find_profile():
        platform = {
            'darwin': [os.path.expanduser('~'), 'Library',
                       'Application Support', 'Firefox', 'profiles.ini'],
            'linux':  [os.path.expanduser('~'), '.mozilla',
                       'firefox', 'profiles.ini'],
            'win32':  [os.getenv('APPDATA', ''), 'Mozilla',
                       'Firefox', 'profiles.ini']}
        try:
            return os.path.join(*platform[sys.platform])
        except KeyError:
            msg = 'Unsupported Operation System ' + sys.platform
            raise FirefoxCookieError(msg)

    @staticmethod
    def parse_profile(profile):
        # TODO Rework required make this able to deale with several Profiles
        config = configparser.ConfigParser()
        config.read(profile)
        path = None
        for section in config.sections():
            if not section.startswith('Profile'):
                continue
            default = False
            try:
                currentpath = config.get(section, 'Path')
                if config.getboolean(section, 'IsRelative'):
                    base = os.path.dirname(profile)
                    currentpath = os.path.join(base, currentpath)
                if config.has_option(section, 'Default'):
                    default = config.getboolean(section, 'Default')
                if default or not path:
                    path = os.path.normpath(currentpath)
            except configparser.NoOptionError:
                if section != 'General':
                    raise FirefoxCookieError('Section is broken ' + section)
        return path


def main():
    profile = FirefoxCookieJar.find_profile()
    path = FirefoxCookieJar.parse_profile(profile)
    cookiejar = FirefoxCookieJar(path + '/cookies.sqlite')

    cookiejar.load()
    out_cookiejar = http.cookiejar.MozillaCookieJar()
    for cookie in cookiejar:
        out_cookiejar.set_cookie(cookie)
    out_cookiejar.save(filename='/dev/stdout',
                       ignore_discard=True,
                       ignore_expires=True)


if __name__ == '__main__':
    main()
