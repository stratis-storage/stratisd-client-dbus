# Copyright 2018 Red Hat, Inc.
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
Used to test udev "add" event in stratisd
"""

import unittest

import subprocess
import time
import random
import string

from stratisd_client_dbus import Manager
from stratisd_client_dbus import ObjectManager
from stratisd_client_dbus import get_object
from stratisd_client_dbus import pools

from stratisd_client_dbus._constants import TOP_OBJECT

from .._misc import Service
from .._misc import LoopBackDevices


def rs(l):
    """
    Generates a random string with the prefix 'stratis_'
    :param l: Length of random part of string
    :return: String
    """
    return 'stratis_{0}'.format(''.join(
        random.choice(string.ascii_uppercase) for _ in range(l)))


class UdevAdd(unittest.TestCase):
    """
    Test udev add event support.
    """

    @staticmethod
    def _create_pool(name, devices):
        """
        Creates a stratis pool
        :param name:    Name of pool
        :param devices:  Devices to use for pool
        :return: Dbus proxy object representing pool.
        """
        ((pool_object_path, _), _, _) = Manager.Methods.CreatePool(
            get_object(TOP_OBJECT),
            {
                'name': name,
                'redundancy': (True, 0),
                'force': False,
                'devices': devices
            }
        )
        return get_object(pool_object_path)

    def _device_files(self, tokens):
        """
        Converts a list of loop back devices to a list of /dev file entries
        :param tokens: Loop back device list
        :return: List of loop back devices
        """
        rc = []
        for t in tokens:
            rc.append(self._lb_mgr.device_file(t))
        return rc

    def setUp(self):
        """
        Common needed things
        """
        self._lb_mgr = LoopBackDevices()
        self.addCleanup(self._clean_up)
        self._service = None

    def _clean_up(self):
        """
        Cleans up the test environment
        :return: None
        """
        if self._service:
            self._service.tearDown()
            self._service = None

        if self._lb_mgr:
            self._lb_mgr.destroy_all()
            self._lb_mgr = None

    @staticmethod
    def _get_pools(name=None):
        """
        Returns a list of the pools or a list with 1 element if name is set and
        found, else empty list
        :param name: Optional filter for pool name
        :return:
        """
        managed_objects = ObjectManager.Methods.GetManagedObjects(
            get_object(TOP_OBJECT), {})

        if name:
            return list(pools(managed_objects, {'Name': name}))
        return list(pools(managed_objects, {}))

    def _start_service(self):
        """
        Starts the service
        :return: None
        """
        if not self._service:
            self._service = Service(not_sim=True)
        self._service.setUp()

    def _stop_service(self):
        """
        Stops the service
        :return: None
        """
        if self._service:
            self._service.tearDown()
            self._service = None

    @staticmethod
    def _settle():
        """
        Wait until udev add is complete for us.
        :return: None
        """
        # What is the best way to ensure we wait long enough for
        # the event to be done, this seems to work for now.
        # pylint: disable=no-member
        subprocess.run(['udevadm', 'settle'], check=True)
        time.sleep(1)

    # pylint: disable=too-many-locals
    def _test_driver(self, number_of_pools, dev_count_pool,
                     some_existing=False):
        """
        We want to test 1..N number of devices in the following scenarios:

        * Devices with no signatures getting hot-plug
        * 1 or more devices in pool
          - All devices present @ startup
          - 1 or more @ startup, but incomplete number of devices at startup
          - 0 @ startup, systematically adding one @ a time

        :param number_of_pools: Number of pools
        :param dev_count_pool: Number of devices in each pool
        :param some_existing: Hotplug some devices before we start the daemon
        :return: None
        """

        pool_data = {}

        self._start_service()

        # Create the pools
        for p in range(0, number_of_pools):
            device_tokens = []

            for i in range(0, dev_count_pool):
                device_tokens.append(self._lb_mgr.create_device(2048))

            pool_name = rs(5)
            UdevAdd._create_pool(pool_name, self._device_files(device_tokens))
            pool_data[pool_name] = device_tokens

        # Start & Stop the service
        self._stop_service()
        self._start_service()

        # We should have all the devices, so pool should exist after toggle
        self.assertEqual(len(UdevAdd._get_pools()), number_of_pools)

        self._stop_service()

        # Unplug all the devices
        for device_tokens in pool_data.values():
            for d in device_tokens:
                self._lb_mgr.unplug(d)

        self._start_service()

        self.assertEqual(len(UdevAdd._get_pools()), 0)

        # Systematically add a device to each pool, checking that the pool
        # isn't assembled until complete
        activation_sequence = []

        pool_names = pool_data.keys()

        for i in range(0, dev_count_pool):
            for p in pool_names:
                activation_sequence.append(pool_data[p][i])

        for device_token in activation_sequence[:-number_of_pools]:
            self._lb_mgr.hotplug(device_token)

            if some_existing:
                self._stop_service()
                self._start_service()
            else:
                self._settle()
            result = UdevAdd._get_pools()
            self.assertEqual(len(result), 0)

        for device_token in activation_sequence[-number_of_pools:]:
            self._lb_mgr.hotplug(device_token)

        self._settle()
        self.assertEqual(len(UdevAdd._get_pools()), number_of_pools)

        for pn in pool_names:
            self.assertEqual(len(self._get_pools(pn)), 1)

        # After this test we need to clean-up in case we are running again
        # from same test fixture
        self._stop_service()
        self._lb_mgr.destroy_devices()

    def test_combinations(self):
        """
        Test for 0..2 pools with 1..3 devices in each pool.
        :return:
        """
        for pools_num in range(0, 3):
            for device_num in range(1, 4):
                print("Testing %d %d" % (pools_num, device_num))
                self._test_driver(pools_num, device_num)

    def test_existing(self):
        """
        While we are adding devices back we will stop start the daemon to ensure
        it can start with one or more devices present and complete when the
        other devices come in later.
        :return: None
        """
        self._test_driver(2, 4, True)

    def _single_pool(self, num_devices, num_hotplugs):
        """
        Creates a single pool with specified number of devices.
        :param num_devices: Number of devices to use for pool
        :param num_hotplugs: Number of extra udev "add" event per devices
        :return: None
        """
        self._start_service()
        result = UdevAdd._get_pools()
        self.assertEqual(len(result), 0)

        device_tokens = []

        for _ in range(0, num_devices):
            device_tokens.append(self._lb_mgr.create_device(2048))

        pool_name = rs(5)
        UdevAdd._create_pool(pool_name, self._device_files(device_tokens))

        self._stop_service()

        # Remove the devices
        for d in device_tokens:
            self._lb_mgr.unplug(d)

        self._start_service()

        for d in device_tokens:
            self._lb_mgr.hotplug(d)

        # Generate unnecessary hot plug adds
        for _ in range(0, num_hotplugs):
            for d in device_tokens:
                self._lb_mgr.generate_udev_add_event(d)

        self._settle()

        result = UdevAdd._get_pools()
        self.assertEqual(len(result), 1)

    def test_simultaneous(self):
        """
        Create a single pool with 16 devices and simulate them being hotplug
        at same time
        :return: None
        """
        self._single_pool(16, 1)

    def test_spurious_adds(self):
        """
        Create a single pool with 16 devices and simulate them being hotplug
        at same time and with spurious additional "add" udev events
        :return: None
        """
        self._single_pool(16, 3)
