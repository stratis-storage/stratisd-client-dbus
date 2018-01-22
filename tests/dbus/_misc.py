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

import abc
import os
import string
import subprocess
import time

from stratisd_client_dbus import get_object
from stratisd_client_dbus._constants import TOP_OBJECT

from hypothesis import strategies

_STRATISD = os.environ['STRATISD']

SIMULATOR = 'sim'
MODE = os.getenv('STRATIS_TEST_MODE', SIMULATOR).lower()
DEVICES = os.getenv('STRATIS_TEST_DEVICES', "").split()


ZERO_BUFFER = bytearray(1024*8)


def wipe_stratus_device(device):
    """
    Wipe the first 8K of the specified device
    :param device: Block device to clear
    :return: None
    """
    # TODO Check to see if this is a stratis device first?
    with open(device, "wb") as disk:
        disk.write(ZERO_BUFFER)


def get_processes(cmd_search_string):
    """
    Walk /proc looking for processes that contain cmd_search_string in the
    cmdline.
    :param cmd_search_string:
    :return: List of tuples (pid, cmdline)
    """
    rc = []
    pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
    for p in pids:
        try:
            cmdline = open(os.path.join('/proc', p, 'cmdline')).read()
            if cmd_search_string in cmdline:
                rc.append((int(p), cmdline))

        except IOError:
            pass
    return rc


class RealDevice(object):
    """
    Offer the same API with real devices as is present for hypothesis
    """
    def __init__(self, devices=None):
        self.device_list = devices

    def example(self):
        return self.device_list


def _device_list(minimum):
    """
    Get a device generating strategy.

    :param int minimum: the minimum number of devices, must be at least 0
    """
    if MODE == SIMULATOR:
        return strategies.lists(
           strategies.text(
              alphabet=string.ascii_letters + "/",
              min_size=1
           ),
           min_size=minimum
        )

    return RealDevice(DEVICES)


def ensure_no_daemon():
    """
    Check for the existence of the stratisd daemon, if it exists kill it!
    :return: None
    """
    # Make sure process is actually gone, sometimes it still exists!
    stratis_pids = get_processes('stratisd')

    while len(stratis_pids) > 0:
        for p, cmd in stratis_pids:
            os.kill(p, 9)
        time.sleep(1)
        stratis_pids = get_processes('stratisd')


class ServiceABC(abc.ABC):
    """
    Abstract base class of Service classes.
    """

    @abc.abstractmethod
    def setUp(self):
        """
        Start the stratisd daemon.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def tearDown(self):
        """
        Stop the stratisd daemon.
        """
        raise NotImplementedError()


class ServiceR(ServiceABC):
    """
    Handle starting and stopping the Rust service.
    """

    def setUp(self):

        ensure_no_daemon()

        if MODE == SIMULATOR:
            self._stratisd = subprocess.Popen([os.path.join(_STRATISD), '--sim'])
        else:
            self._stratisd = subprocess.Popen([os.path.join(_STRATISD),
                                               '--debug'])
        # It takes some time for the service to be ready to use, lets wait
        # until we can talk to the dbus service before we continue, testing
        # shows that the daemon appears to be ready in about 100ms.
        limit = time.time() + 10.0
        while time.time() <= limit:
            try:
                get_object(TOP_OBJECT)
                break
            except:
                time.sleep(0.1)

    def tearDown(self):
        """
        Stop the stratisd simulator and daemon.
        """
        # pylint: disable=no-member
        self._stratisd.terminate()
        self._stratisd.wait()

        ensure_no_daemon()

        # TODO: Need to make this more selective...
        subprocess.call(["/usr/sbin/dmsetup", "remove_all"])

        # Clear any real devices
        for d in DEVICES:
            wipe_stratus_device(d)


Service = ServiceR
