import os
import windows_service


def test_windows_service_origin_and_no_voice_autostart(monkeypatch):
    calls = []
    marker = object()
    monkeypatch.setattr('server.create_app', lambda **kw: (calls.append(kw), marker)[1])
    monkeypatch.setattr('dotenv.load_dotenv', lambda *_: None)
    monkeypatch.setenv('AMBI_FRONTEND_ORIGINS', 'http://unrelated.invalid')
    assert windows_service.create_windows_app() is marker
    assert calls == [{'seed': False, 'auto_start': False}]
    assert os.environ['AMBI_FRONTEND_ORIGINS'] == 'http://127.0.0.1:8767,http://localhost:8767'


def test_windows_service_binds_only_loopback(monkeypatch):
    calls = []
    marker = object()
    monkeypatch.setattr(windows_service, 'create_windows_app', lambda: marker)
    monkeypatch.setattr('uvicorn.run', lambda *args, **kw: calls.append((args, kw)))
    windows_service.main()
    assert calls == [((marker,), {'host': '127.0.0.1', 'port': 8767, 'access_log': False})]
