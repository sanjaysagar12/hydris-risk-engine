from hydris_risk.io.input_loader import load_factories


def write(tmp_path, text, encoding="utf-8"):
    p = tmp_path / "f.csv"
    p.write_text(text, encoding=encoding)
    return p


def test_valid_file_with_aliases_case_and_whitespace(tmp_path):
    p = write(tmp_path, " Site_ID , SITE_NAME ,Latitude, Longitude ,Country\nA, Mill A ,11.1,77.3, India \nB,Mill B,12,78,\n")
    fs, issues = load_factories(p)
    assert issues == [] and [f.site_id for f in fs] == ["A", "B"]
    assert fs[0].site_name == "Mill A" and fs[0].lat == 11.1 and fs[0].country == "India" and fs[1].country is None


def test_excel_bom_is_accepted(tmp_path):
    fs, issues = load_factories(write(tmp_path, "site_id,site_name,lat,lon\nA,A,1,2\n", encoding="utf-8-sig"))
    assert len(fs) == 1 and not issues


def test_bad_rows_reported_and_skipped(tmp_path):
    p = write(
        tmp_path,
        "site_id,site_name,lat,lon\n"
        "A,Good,11,77\n"          # row 2
        "B,BadLat,abc,77\n"       # row 3: not a number
        "C,Swapped,106.6,10.8\n"  # row 4: lat out of range, lon valid as a latitude -> swapped
        "D,Range,95,200\n"        # row 5: out of range both ways
        ",NoId,1,2\n"             # row 6: missing site_id
        "E,Good2,12,78\n",        # row 7
    )
    fs, issues = load_factories(p)
    assert [f.site_id for f in fs] == ["A", "E"]
    errs = {i.row: i.message for i in issues if i.level == "error"}
    assert set(errs) == {3, 4, 5, 6}
    assert "must be numbers" in errs[3]
    assert "look swapped" in errs[4]
    assert "lat" in errs[5] and "lon" in errs[5] and "swapped" not in errs[5]
    assert "site_id" in errs[6]


def test_duplicates_and_identical_coordinates(tmp_path):
    p = write(tmp_path, "site_id,site_name,lat,lon\nA,A,11,77\nA,A again,12,78\nB,B,11,77\n")
    fs, issues = load_factories(p)
    assert [f.site_id for f in fs] == ["A", "B"]
    assert {(i.level, i.row) for i in issues} == {("error", 3), ("warning", 4)}
    assert any("duplicate site_id" in i.message for i in issues)
    assert any("same coordinates as site A" in i.message for i in issues)


def test_missing_required_columns(tmp_path):
    fs, issues = load_factories(write(tmp_path, "site_id,lat\nA,1\n"))
    assert fs == [] and issues[0].row is None and "site_name" in issues[0].message and "lon" in issues[0].message
