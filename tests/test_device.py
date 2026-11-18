"""Offline tests for the device layer (no iPhone needed).

Run with:  py -3.12 -m unittest discover -s tests -v
"""
from __future__ import annotations

import plistlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iphone_app_manager.device import (  # noqa: E402
    DeviceError, DeviceService, ErrorKind, ToolResult, classify_failure, parse_app_list,
)

SAMPLE = plistlib.dumps([
    {"CFBundleIdentifier": "com.example.weather", "CFBundleDisplayName": "Weather Pro",
     "CFBundleName": "WeatherPro", "CFBundleShortVersionString": "3.2.1", "CFBundleVersion": "321",
     "ApplicationType": "User"},
    {"CFBundleIdentifier": "com.example.noname", "CFBundleVersion": "7"},
    {"CFBundleDisplayName": "No bundle id - skipped"},
], fmt=plistlib.FMT_XML)


class ParseTests(unittest.TestCase):
    def test_parses_fields_and_fallbacks(self):
        apps = parse_app_list(SAMPLE)
        self.assertEqual(len(apps), 2)
        self.assertEqual((apps[0].name, apps[0].bundle_id, apps[0].version),
                         ("Weather Pro", "com.example.weather", "3.2.1"))
        self.assertEqual(apps[1].name, "com.example.noname")  # falls back to bundle id
        self.assertEqual(apps[1].version, "7")                # falls back to CFBundleVersion

    def test_ignores_leading_noise(self):
        self.assertEqual(len(parse_app_list(b"some banner\r\n" + SAMPLE)), 2)

    def test_invalid_xml(self):
        with self.assertRaises(DeviceError) as ctx:
            parse_app_list(b"<?xml version='1.0'?><plist><array><dict>")
        self.assertIs(ctx.exception.kind, ErrorKind.PARSE)

    def test_error_text_instead_of_xml(self):
        with self.assertRaises(DeviceError) as ctx:
            parse_app_list(b"No device found.\n")
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "No device found.": ErrorKind.NO_DEVICE,
            "ERROR: No device found!": ErrorKind.NO_DEVICE,
            "Could not connect to lockdownd: Pairing dialog response pending (-19)": ErrorKind.NOT_TRUSTED,
            "ERROR: Could not connect to lockdownd: Invalid HostID (-21)": ErrorKind.NOT_TRUSTED,
            "Could not connect to lockdownd: User denied pairing (-18)": ErrorKind.NOT_TRUSTED,
            "Could not connect to lockdownd: Password protected (-17)": ErrorKind.LOCKED,
            "segfault": ErrorKind.UNKNOWN,
        }
        for text, kind in cases.items():
            with self.subTest(text=text):
                self.assertIs(classify_failure(text), kind)


class ServiceTests(unittest.TestCase):
    def make_service(self, responses):
        def runner(exe, args, timeout):
            return responses(Path(exe).name, list(args))
        return DeviceService(runner=runner, installer=Path("ideviceinstaller.exe"),
                             info_tool=Path("ideviceinfo.exe"))

    def test_snapshot_success(self):
        def responses(exe, args):
            if exe == "ideviceinfo.exe":
                return ToolResult(0, b"Test iPhone\n" if "DeviceName" in args else b"26.1\n", b"")
            return ToolResult(0, SAMPLE, b"")
        device, apps = self.make_service(responses).load_snapshot()
        self.assertEqual((device.name, device.ios_version), ("Test iPhone", "26.1"))
        self.assertEqual(len(apps), 2)

    def test_disconnected(self):
        svc = self.make_service(lambda exe, args: ToolResult(255, b"", b"ERROR: No device found!\n"))
        with self.assertRaises(DeviceError) as ctx:
            svc.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NO_DEVICE)

    def test_not_trusted(self):
        err = b"ERROR: Could not connect to lockdownd: Pairing dialog response pending (-19)\n"
        svc = self.make_service(lambda exe, args: ToolResult(255, b"", err))
        with self.assertRaises(DeviceError) as ctx:
            svc.load_snapshot()
        self.assertIs(ctx.exception.kind, ErrorKind.NOT_TRUSTED)


if __name__ == "__main__":
    unittest.main()
