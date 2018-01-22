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


import tempfile
import uuid

from hypothesis import strategies

_STRATISD = os.environ['STRATISD']

SIMULATOR = 'sim'
MODE = os.getenv('STRATIS_TEST_MODE', SIMULATOR).lower()


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

class ServiceABC(abc.ABC):
    """
    Abstract base class of Service classes.
    """

    @abc.abstractmethod
    def setUp(self):
        """
        Start the stratisd daemon with the simulator.
        """
        raise NotImplementedError()

    def tearDown(self):
        """
        Stop the stratisd simulator and daemon.
        """
        # pylint: disable=no-member
        self._stratisd.terminate()
        self._stratisd.wait()


class ServiceR(ServiceABC):
    """
    Handle starting and stopping the Rust service.
    """
    def __init__(self, not_sim=False):
        super(ServiceR, self).__init__()
        self._not_sim = not_sim

    def setUp(self):
        if MODE == SIMULATOR and not self._not_sim:
            self._stratisd = subprocess.Popen([os.path.join(_STRATISD),
                                               '--sim'])
        else:
            self._stratisd = subprocess.Popen([os.path.join(_STRATISD),
                                               '--debug'])


Service = ServiceR


BIN = os.getenv('STRATIS_LOSETUP_BIN', "/usr/sbin/losetup")


class LoopBackDevices(object):
    """
    Class for creating and managing loop back devices which are needed for
    specific types of udev event testing.
    """

    def __init__(self):
        """
        Class constructor which creates a temporary directory to store backing
        file in.
        """
        self.dir = tempfile.mkdtemp('_stratis_loop_back')
        self.count = 0
        self.devices = {}

    def create_device(self, size_mib):
        """
        Create a new loop back device, sparse backing file and attaching it.

        Note: The first time a loop back device is known it will generate
        a udev "add" event, subsequent backing file changes do not, thus we
        will need to generate it synthetically.
        :param size_mib:
        :return: opaque handle, done as device representing block device will
                 change.
        """
        backing_file = self.dir + '/block_device_%d' % self.count
        self.count += 1

        with open(backing_file, 'ab') as bd:
            bd.truncate(size_mib * (1024 * 1024))

        result = subprocess.run([BIN, '-f', '--show', backing_file],
                                check=True, stdout=subprocess.PIPE)
        device = str.strip(result.stdout.decode("utf-8"))
        token = uuid.uuid4()
        self.devices[token] = (device, backing_file)
        return token

    def unplug(self, token):
        """
        Remove the device from the /dev tree, but doesn't remove backing file
        :param token: Opaque representation of some loop back device
        :return: None
        """
        if token in self.devices:
            (device, backing_file) = self.devices[token]
            subprocess.run([BIN, '-d', device], check=True)
            self.devices[token] = (None, backing_file)

    def generate_udev_add_event(self, token):
        """
        Synthetically create "add" udev event for this loop back device
        :param token: Opaque representation of some loop back device
        :return: None
        """
        if token in self.devices:
            (device, _) = self.devices[token]

            if device:
                device_name = device.split('/')
                with open("/sys/block/%s/uevent" % device_name[-1], "w") as e:
                    e.write("add")

    def hotplug(self, token):
        """
        Attaches an existing backing file to a loop back device
        :param token: Opaque representation of some loop back device
        :return:
        """
        if token in self.devices:
            (_, backing_file) = self.devices[token]

            result = subprocess.run([BIN, '-f', '--show', backing_file],
                                    check=True, stdout=subprocess.PIPE)
            device = str.strip(result.stdout.decode("utf-8"))
            self.devices[token] = (device, backing_file)

            # Make sure an add occurs
            self.generate_udev_add_event(token)

    def device_file(self, token):
        """
        Return the device block device full name for a loopback token
        :param token: Opaque representation of some loop back device
        :return: Full file path or None if not currently attached
        """
        if token in self.devices:
            return self.devices[token][0]

    def destroy_devices(self):
        """
        Detach loopbacks and remove backing files
        :return:
        """
        for (device, backing_file) in self.devices.values():
            if device is not None:
                subprocess.run([BIN, '-d', device], check=True)
            os.remove(backing_file)

        self.devices = {}
        self.count = 0

    def destroy_all(self):
        """
        Detach all the devices and delete the file(s) and directory!
        :return: None
        """
        self.destroy_devices()
        os.rmdir(self.dir)
        self.dir = None
