import pathlib

from career_bot.planning.spark.reroll import (
    choose_spark_list,
    extract_reroll_options,
    factor_ids_from_row,
)


ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_choose_prefers_more_blue_stars():
    assert choose_spark_list([[101], [102]], ROOT) == 2


def test_choose_uses_pink_when_blue_equal():
    assert choose_spark_list([[101, 1101], [101, 1102]], ROOT) == 2


def test_choose_uses_green_when_blue_and_pink_equal():
    assert choose_spark_list([[101, 1101, 10060101], [101, 1101, 10060102]], ROOT) == 2


def test_choose_uses_white_count_not_white_stars():
    assert choose_spark_list([[2012603], [2012601, 2003501]], ROOT) == 2


def test_choose_returns_one_on_full_tie():
    assert choose_spark_list([[101, 1101, 10060101], [101, 1101, 10060101]], ROOT) == 1


def test_factor_ids_from_row_reads_factor_info_array_when_factor_id_array_missing():
    assert factor_ids_from_row({"factor_info_array": [{"factor_id": "301"}, {"factor_id": 0}, {}, None]}) == [301]


def test_extract_reroll_options_maps_by_lottery_id_not_array_order():
    response = {"data": {"single_mode_factor_lottery_common": {"factor_select_info_array": [
        {"lottery_id": 2, "factor_info_array": [{"factor_id": 501}]},
        {"lottery_id": 1, "factor_info_array": [{"factor_id": 301}]},
    ]}}}

    assert extract_reroll_options(response) == [[301], [501]]


def test_captured_example_chooses_finish_2():
    original = [301, 3302, 10060101]
    rerolled = [501, 1102, 2012601, 10060101]

    assert choose_spark_list([original, rerolled], ROOT) == 2