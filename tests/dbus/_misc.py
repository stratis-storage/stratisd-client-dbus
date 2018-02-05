# Copyright 2016 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Miscellaneous methods to support testing.
"""

import os
import string
import subprocess
import time

from hypothesis import strategies

from stratisd_client_dbus import get_object
from stratisd_client_dbus._constants import TOP_OBJECT

_STRATISD = os.environ['STRATISD']


def _device_list(minimum):
    """
    Get a device generating strategy.

    :param int minimum: the minimum number of devices, must be at least 0
    """
    return strategies.lists(
       strategies.text(
          alphabet=string.ascii_letters + "/",
          min_size=1
       ),
       min_size=minimum
    )


class Service(object):
    """
    Handle starting and stopping the Rust service.
    """

    def setUp(self):
        """
        Starts up the stratisd daemeon and waits up to 10 seconds for it to be
        ready, checking every 100ms.
        :return: None
        """
        self._stratisd = subprocess.Popen([os.path.join(_STRATISD), '--sim'])

        limit = time.time() + 10.0
        while time.time() <= limit:
            try:
                get_object(TOP_OBJECT)
                break
            # pylint: disable=bare-except
            except:
                time.sleep(0.1)

    def tearDown(self):
        """
        Stop the stratisd simulator and daemon.
        """
        # pylint: disable=no-member
        self._stratisd.terminate()
        self._stratisd.wait()
