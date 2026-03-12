from kcd_gfx_toolbox.avm1.pcode_utils import extract_label_from_line, strip_label


def test_extract_label_from_line_with_label():
    pcode_sample = "loc6454: Push register1"
    rest_of_line, label = extract_label_from_line(pcode_sample)
    assert label == "loc6454"
    assert rest_of_line == "Push register1"


def test_extract_label_from_line_without_label():
    pcode_sample = "StoreRegister 3"
    rest_of_line, label = extract_label_from_line(pcode_sample)
    assert label is None
    assert rest_of_line == "StoreRegister 3"


def test_strip_label():
    assert strip_label("loc456: Push register3") == "Push register3"
    assert strip_label("Push register3") == "Push register3"
    assert strip_label("L9:If loc998") == "If loc998"
