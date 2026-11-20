from mt5_mcp.mql5.hostpath import host_paths


def test_z_path_becomes_posix():
    assert host_paths(r"json: Z:\home\v\out\Moving Average.json") == "json: /home/v/out/Moving Average.json"


def test_diagnostic_keeps_line_and_col():
    assert host_paths(r"Z:\w\src\A.mq5:12:5: error 157: x") == "/w/src/A.mq5:12:5: error 157: x"


def test_lowercase_drive_and_trailing_prose():
    assert host_paths(r"not a compiled .ex5 file: z:\w\a.ex5") == "not a compiled .ex5 file: /w/a.ex5"


def test_other_drives_and_posix_unchanged():
    for s in (r"C:\users\abc\x.htm", "/already/posix", r"reports\x", r"XYZ:\no"):
        assert host_paths(s) == s


def test_several_paths_over_lines():
    assert host_paths("json: Z:\\a\\b.json\nreport: Z:\\a\\b.htm") == "json: /a/b.json\nreport: /a/b.htm"


def test_root():
    assert host_paths("Z:\\") == "/"
