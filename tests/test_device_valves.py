import asyncio
import datetime
import struct
from typing import Type
from zoneinfo import ZoneInfo

import freezegun
import pytest
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClient  # type: ignore - this is a valid import
from mockito import ANY, expect, mock, verify, when

import melnor_bluetooth.device as device_module
from melnor_bluetooth.constants import (
    BATTERY_UUID,
    MANUFACTURER_UUID,
    VALVE_MANUAL_SETTINGS_UUID,
    VALVE_MANUAL_STATES_UUID,
)
from melnor_bluetooth.device import Device, Valve
from tests.constants import TEST_UUID

zone_manual_setting_bytes = struct.pack(
    ">?HH?HH?HH?HH",
    # Valve 1
    True,
    5,
    5,
    # Valve 2
    True,
    10,
    10,
    # Valve 3
    True,
    15,
    15,
    # Valve 4
    True,
    20,
    20,
)


@pytest.fixture
def ble_device_mock() -> BLEDevice:
    """Mocks a BLEDevice object"""

    ble_device = mock(spec=BLEDevice)
    ble_device.address = TEST_UUID
    ble_device.details = {"name": "Test"}
    ble_device.rssi = 6

    ble_device.set_disconnected_callback = mock()

    return ble_device


@pytest.fixture
def client_mock() -> Type:
    """Mock a BleakClient"""

    c_mock = mock(spec=BleakClient)

    connect = asyncio.Future()
    connect.set_result(c_mock)

    when(device_module).establish_connection(
        client_class=ANY,
        device=ANY,
        name=ANY,
        disconnected_callback=ANY,
        max_attempts=ANY,
    ).thenReturn(connect)

    read_manufacturer = asyncio.Future()
    read_manufacturer.set_result(b"111110400")
    when(c_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(read_manufacturer)

    when(c_mock).connect(timeout=60).thenReturn(connect)

    return c_mock


class TestValveZone:
    def test_zone_update_state(self, client_mock, ble_device_mock):
        device = Device(ble_device=ble_device_mock)

        device.zone1.update_state(zone_manual_setting_bytes, VALVE_MANUAL_SETTINGS_UUID)

        assert device.zone1.is_watering == True
        assert device.zone1.manual_watering_minutes == 5

    def test_zone_properties(self, client_mock, ble_device_mock):
        device = Device(ble_device=ble_device_mock)

        device.zone1.is_watering = True

        assert device.zone1.manual_watering_minutes == 20

    def test_zone_defaults(self, client_mock, ble_device_mock):
        device = Device(ble_device=ble_device_mock)

        zone = Valve(0, device)

        assert zone.is_watering == False
        assert zone.manual_watering_minutes == 20

    def test_zone_byte_payload(self, client_mock, ble_device_mock):
        device = Device(ble_device=ble_device_mock)
        zone = Valve(0, device)

        zone.is_watering = True
        zone.manual_watering_minutes = 10

        assert zone._manual_setting_bytes() == b"\x01\x00\n\x00\n"  # type: ignore


class TestDevice:
    async def test_properties(self, client_mock, ble_device_mock):

        device = Device(ble_device=ble_device_mock)

        await device.connect()

        assert device.name == "4 Valve Timer"
        assert device.model == "11111"
        assert device.mac == TEST_UUID
        assert device.valve_count == 4
        assert device.rssi == ble_device_mock.rssi

    async def test_get_item(self, client_mock, ble_device_mock):
        device = Device(ble_device=ble_device_mock)

        await device.connect()

        assert device["zone1"] is device.zone1
        assert device["zone2"] is device.zone2
        assert device["zone3"] is device.zone3
        assert device["zone4"] is device.zone4

    async def test_1_valve_device(self, client_mock, ble_device_mock):

        read_manufacturer = asyncio.Future()
        read_manufacturer.set_result(b"111110100")
        when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
            read_manufacturer
        )

        device = Device(ble_device=ble_device_mock)

        await device.connect()

        assert device.zone1 is not None
        assert device.zone2 is None
        assert device.zone3 is None
        assert device.zone4 is None

    async def test_2_valve_device(self, client_mock, ble_device_mock):

        device = Device(ble_device=ble_device_mock)

        read_manufacturer = asyncio.Future()
        read_manufacturer.set_result(b"111110200")

        when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
            read_manufacturer
        )

        await device.connect()

        assert device.zone1 is not None
        assert device.zone2 is not None
        assert device.zone3 is None
        assert device.zone4 is None

    async def test_1_valve_has_all_bytes(self, client_mock, ble_device_mock):

        read_manufacturer = asyncio.Future()
        read_manufacturer.set_result(b"111110100")
        when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
            read_manufacturer
        )

        device = Device(ble_device=ble_device_mock)

        await device.connect()

        device.zone1.is_watering = True
        device.zone1.manual_watering_minutes = 10

        assert (
            (
                device._valves[0]._manual_setting_bytes()  # type:ignore
                + device._valves[1]._manual_setting_bytes()  # type:ignore
                + device._valves[2]._manual_setting_bytes()  # type:ignore
                + device._valves[3]._manual_setting_bytes()  # type:ignore
            )
            == b"\x01\x00\n\x00\n\x00\x00\x14\x00\x14\x00\x00\x14\x00\x14\x00\x00\x14\x00\x14"  # noqa: E501
        )

    async def test_1_valve_has_internal_valves(self, client_mock, ble_device_mock):

        read_manufacturer = asyncio.Future()
        read_manufacturer.set_result(b"111110100")
        when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
            read_manufacturer
        )

        device = Device(ble_device=ble_device_mock)

        await device.connect()

        device.zone1.is_watering = True
        device.zone1.manual_watering_minutes = 10

        assert device.zone1 is not None
        assert device.zone2 is None
        assert device.zone3 is None
        assert device.zone4 is None

        assert device._valves[1] is not None  # type:ignore
        assert device._valves[2] is not None  # type:ignore
        assert device._valves[3] is not None  # type:ignore

    async def test_device_connect_lock(self, client_mock, ble_device_mock):
        with expect(BleakClient, times=1).connect():
            device = Device(ble_device=ble_device_mock)

            success = asyncio.Future()

            when(BleakClient).connect().thenReturn(success)
            when(device_module).BleakClient(ble_device_mock).thenReturn(client_mock)

            read_manufacturer = asyncio.Future()
            read_manufacturer.set_result(b"111110100")
            when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
                read_manufacturer
            )

            # We'll verify we only call the bleak client connect once
            loop = asyncio.get_event_loop()
            one = loop.create_task(device.connect())
            two = loop.create_task(device.connect())
            three = loop.create_task(device.connect())
            four = loop.create_task(device.connect())

            success.set_result(True)

            # await the tasks to ensure they're done
            await asyncio.gather(one, two, three, four)

    async def test_device_connect_noop_when_connected(
        self, client_mock, ble_device_mock
    ):
        with expect(BleakClient, times=1).connect():

            device = Device(ble_device=ble_device_mock)

            success = asyncio.Future()
            success.set_result(True)

            when(BleakClient).connect().thenReturn(success)
            when(device_module).BleakClient(ble_device_mock).thenReturn(client_mock)

            read_manufacturer = asyncio.Future()
            read_manufacturer.set_result(b"111110100")
            when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
                read_manufacturer
            )

            await device.connect()
            await device.connect()
            await device.connect()
            await device.connect()

    @freezegun.freeze_time(datetime.datetime.now(tz=ZoneInfo("UTC")))
    async def test_fetch(self, client_mock, ble_device_mock):
        device = Device(ble_device=ble_device_mock)

        read_battery = asyncio.Future()
        read_battery.set_result(b"\x02\x85")

        read_manufacturer = asyncio.Future()
        read_manufacturer.set_result(b"111110400")

        read_manual_settings = asyncio.Future()
        read_manual_settings.set_result(
            struct.pack(
                ">?HH?HH?HH?HH",
                # Valve 1
                False,
                0,
                0,
                # Valve 2
                False,
                0,
                0,
                # Valve 3
                False,
                0,
                0,
                # Valve 4
                False,
                0,
                0,
            )
        )

        read_manual_state = asyncio.Future()
        read_manual_state.set_result(
            struct.pack(
                ">bIbIbIbI",
                # Valve 1
                1,
                4294967295,
                # Valve 2
                1,
                0,
                # Valve 3
                1,
                0,
                # Valve 4
                1,
                0,
            )
        )

        when(client_mock).read_gatt_char(MANUFACTURER_UUID).thenReturn(
            read_manufacturer
        )

        when(client_mock).read_gatt_char(BATTERY_UUID).thenReturn(read_battery)

        when(client_mock).read_gatt_char(VALVE_MANUAL_SETTINGS_UUID).thenReturn(
            read_manual_settings
        )

        when(client_mock).read_gatt_char(VALVE_MANUAL_STATES_UUID).thenReturn(
            read_manual_state
        )

        await device.connect()

        await device.fetch_state()

        verify(client_mock).read_gatt_char(VALVE_MANUAL_SETTINGS_UUID)

        assert device.battery_level == 30
        # assert device.brand == MELNOR

        assert device.zone1.is_watering is False
        assert device.zone1.manual_watering_minutes == 0
        # TODO: Test this more aggressively in date utils
        assert device.zone1.watering_end_time != 0

        assert device.zone2 is not None
        assert device.zone2.is_watering is False
        assert device.zone2.manual_watering_minutes == 0
        assert device.zone2.watering_end_time == 0

        assert device.zone3 is not None
        assert device.zone3.is_watering is False
        assert device.zone3.manual_watering_minutes == 0
        assert device.zone3.watering_end_time == 0

        assert device.zone4 is not None
        assert device.zone4.is_watering is False
        assert device.zone4.manual_watering_minutes == 0
        assert device.zone4.watering_end_time == 0

    def test_str(self, snapshot, ble_device_mock):
        device = Device(ble_device=ble_device_mock)

        actual = device.__str__()

        assert actual == snapshot
