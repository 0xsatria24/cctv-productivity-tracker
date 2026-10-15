"""Windows SCM host for the same supervisor. No GUI or pywin32 dependency."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from threading import Event

from .supervisor import supervise


def run_service(config_path):
    if os.name != 'nt':
        raise RuntimeError('Windows SCM is available only on Windows')
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    if set(config) != {'name', 'command', 'state_dir', 'health_url', 'working_directory'}:
        raise ValueError('Invalid service configuration')
    stop = Event()
    service = ctypes.WinDLL('advapi32', use_last_error=True)
    class ServiceStatus(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in ('type', 'state', 'accepted', 'win_error', 'service_error', 'checkpoint', 'wait_hint')]
    Main = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
    Handler = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
    class Entry(ctypes.Structure):
        _fields_ = [('name', wintypes.LPWSTR), ('main', Main)]
    service.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, Handler, ctypes.c_void_p]
    service.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    service.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(ServiceStatus)]
    service.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(Entry)]
    handle = None
    def report(state, exit_code=0):
        value = ServiceStatus(0x10, state, 5 if state == 4 else 0, 1066 if exit_code else 0, exit_code, 1 if state in (2, 3) else 0, 60000 if state in (2, 3) else 0)
        service.SetServiceStatus(handle, ctypes.byref(value))
    @Handler
    def control(code, event, data, context):
        if code in (1, 5):  # STOP / SHUTDOWN
            report(3)
            stop.set()
        return 0
    @Main
    def main(argc, argv):
        nonlocal handle
        handle = service.RegisterServiceCtrlHandlerExW(config['name'], control, None)
        if not handle:
            return
        report(2)
        try:
            os.chdir(config['working_directory'])
            report(4)
            result = supervise(config['command'], config['state_dir'], health_url=config['health_url'], stop=stop)
            report(1, result)
        except Exception:
            report(1, 1)
    table = (Entry * 2)(Entry(config['name'], main), Entry(None, Main()))
    if not service.StartServiceCtrlDispatcherW(table):
        raise RuntimeError('Start this host through Windows Services (SCM)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    run_service(parser.parse_args().config)
