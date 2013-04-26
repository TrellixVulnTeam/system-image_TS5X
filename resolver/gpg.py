# Copyright (C) 2013 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Handle GPG signature verification."""

__all__ = [
    'Context',
    'get_pubkey',
    ]


import os
import gpgme
import shutil
import tempfile

from contextlib import ExitStack
from datetime import datetime, timedelta
from functools import partial
from resolver.cache import Cache
from resolver.download import Downloader
from resolver.helpers import atomic
from urllib.parse import urljoin


class Context:
    def __init__(self, pubkey_path, home=None):
        self.pubkey_path = pubkey_path
        self.home = home
        self._ctx = None
        self._withstack = ExitStack()
        self.import_result = None

    def __enter__(self):
        try:
            # If any errors occur, pop the exit stack to clean up any
            # temporary directories.
            if self.home is None:
                # No $GNUPGHOME specified, so use a temporary directory, but
                # be sure to arrange for the tempdir to be deleted no matter
                # what.
                home = tempfile.mkdtemp(prefix='.otaupdate')
                self._withstack.callback(partial(shutil.rmtree, home))
            else:
                home = self.home
            # Create the context, using the $GNUPGHOME.
            old_gnupghome = os.environ.get('GNUPGHOME')
            if old_gnupghome is None:
                self._withstack.callback(
                    partial(os.environ.__delitem__, 'GNUPGHOME'))
            else:
                self._withstack.callback(
                    partial(os.environ.__setitem__,
                            'GNUPGHOME', old_gnupghome))
            os.environ['GNUPGHOME'] = home
            self._ctx = gpgme.Context()
            self._withstack.callback(partial(setattr, self, '_ctx', None))
            with open(self.pubkey_path, 'rb') as fp:
                self.import_result = self._ctx.import_(fp)
        except:
            # Restore all context and re-raise the exception.
            self._withstack.pop_all().close()
            raise
        else:
            return self

    def __exit__(self, *exc_details):
        self._withstack.pop_all().close()
        # Don't swallow exceptions.
        return False

    def verify(self, signature, signed_text):
        # Since we always use detached signatures, the third argument,
        # i.e. `plaintext` can always be None.
        return self._ctx.verify(signature, signed_text, None)


def get_pubkey(cache=None):
    """Make sure we have the pubkey, downloading it if necessary."""
    # BAW 2013-04-26: Ultimately, it's likely that the pubkey will be
    # placed on the file system at install time.
    if cache is None:
        from resolver.config import config
        cache = Cache(config)
    pubkey_path = cache.get_path('phablet.pubkey.asc')
    if pubkey_path is None:
        url = urljoin(cache.config.service.base, 'phablet.pubkey.asc')
        with Downloader(url) as response:
            pubkey = response.read().decode('utf-8')
        # Now, put the pubkey in the cache and update the cache with an
        # insanely long timeout for the file.
        pubkey_path = os.path.join(cache.config.cache.directory,
                                   'phablet.pubkey.asc')
        when = datetime.now() + timedelta(days=365*10)
        # The pubkey is ASCII armored so the default utf-8 is good enough.
        with atomic(pubkey_path) as fp:
            fp.write(pubkey)
            cache.update('phablet.pubkey.asc', when)
    return pubkey_path
