#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
import configparser
import contextlib
import os
import sys
import tempfile
import typing
import sqlite3
import http.cookiejar
from pathlib import Path


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
            sql = stack.enter_context(
                tempfile.NamedTemporaryFile(suffix=".sqlite"))
            fin = stack.enter_context(open(filename, "rb"))

            # Copy sqlite to tmpfile for avoid sqlite lock issues
            [sql.write(x) for x in iter(fin.read, b'')]

            sqlite = stack.enter_context(sqlite3.connect(sql.name))
            # get a result as dict
            sqlite.row_factory = sqlite3.Row

            for cookie in self._cookiefromsql(sqlite):
                if (ignore_expires and cookie.is_expired) or \
                   (ignore_discard and cookie.discard):
                       continue
                self.set_cookie(cookie)

    def _cookiefromsql(self, sqlite: sqlite3.Connection) -> typing.Iterator[http.cookiejar.Cookie]:
        raise NotImplementedError


class FirefoxCookieJar(SqliteCookieJar):

    def __init__(self,filename=None, delayload=False, policy=None):
        super().__init__(filename, delayload, policy)
        if not filename:
            # if no filename is given use default Profile
            self.filebyprofile()

    def _cookiefromsql(self, sqlite):
        keys = ['host', 'path', 'isSecure', 'expiry', 'name', 'value']
        query = 'select {keys} from moz_cookies'.format(keys=','.join(keys))

        cur = sqlite.cursor()
        cur.execute(query)
        for item in cur.fetchall():
            try:
                startisdot = item['host'].startswith('.')
                cookie = http.cookiejar.Cookie(0,
                                               item['name'],
                                               item['value'],
                                               None, False,
                                               item['host'],
                                               startisdot,
                                               startisdot,
                                               item['path'], False,
                                               item['isSecure'],
                                               item['expiry'],
                                               item['expiry'],
                                               None, None, {})
                yield cookie
            except KeyError as exp:
                msg = f"Coudn't convert db entry {item} to cookie"
                raise SqliteCookieError(msg) from exp

    def filebyprofile(self, name: str = None) -> str:
        '''
        This method parses the Firefox profile to determine the path where the
        cookie database is stored.

            name ~ Name of the profile to be scanned, or None then the default profile is used.
        '''
        platform = {
            'darwin': Path(Path.home(), 'Library',
                           'Application Support', 'Firefox', 'profiles.ini'),
            'linux': Path(Path.home(), '.mozilla', 'firefox', 'profiles.ini'),
            'win32': Path(os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\profiles.ini')),
        }
        try:
            inifile = platform[sys.platform]
        except KeyError as err:
            msg = f"Unsupported Operation System {sys.platform}"
            raise FirefoxCookieError(msg) from err

        config = configparser.ConfigParser()
        config.read(inifile)
        profiles = filter(lambda x: x.startswith('Profile'),
                          config.sections())
        for profile in profiles:
            try:
                path = Path(config.get(profile, 'Path'))
                if config.getboolean(profile, 'IsRelative'):
                    path = inifile.parent.joinpath(path)
                if (name and config.get(profile, 'Name') == name) or \
                   config.getboolean(profile, 'Default', fallback=False):

                    # to satisfiy mypy convert to string here
                    cookie_db = path.joinpath('cookies.sqlite')
                    self.filename = str(cookie_db.absolute())
                    return self.filename
            except configparser.NoOptionError as err:
                raise FirefoxCookieError(
                    f"Don't understand Profile {profile} in {inifile}") from err
        raise FirefoxCookieError(f"No default Profile in {inifile}")


def main():
    cookiejar = FirefoxCookieJar()
    cookiejar.load()

    out_cookiejar = http.cookiejar.MozillaCookieJar()
    for cookie in cookiejar:
        out_cookiejar.set_cookie(cookie)
    out_cookiejar.save(filename='/dev/stdout',
                       ignore_discard=True,
                       ignore_expires=True)


if __name__ == '__main__':
    main()
