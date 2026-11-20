from routers.v1.lots import _HTTP_URL_FIELDS, saved_lot_to_basic


class _Row:
    def __init__(self, **values):
        for name, value in values.items():
            setattr(self, name, value)


def test_saved_lot_row_maps_to_basic_lot():
    lot = saved_lot_to_basic(
        _Row(
            lot_id="46314494",
            site=2,
            base_site="iaai",
            year=2015,
            make="Lexus",
            model="RX 350",
            vin="2T2ZK1BA1FC193251",
        )
    )

    assert lot is not None
    assert lot.lot_id == 46314494
    assert lot.site == 2
    assert lot.base_site == "iaai"
    assert lot.year == 2015
    assert lot.make == "Lexus"
    assert lot.model == "RX 350"
    assert lot.vin == "2T2ZK1BA1FC193251"


def test_invalid_image_url_is_dropped_instead_of_losing_the_lot():
    assert {"link", "link_img_hd", "link_img_small"} <= _HTTP_URL_FIELDS

    lot = saved_lot_to_basic(
        _Row(
            lot_id="42",
            site=1,
            base_site="copart",
            year=2018,
            make="Mazda",
            model="6",
            link="not-a-url",
            link_img_hd=["https://cs.copart.com/photo.jpg", "not-a-url"],
            link_img_small=["notaurl"],
        )
    )

    assert lot is not None
    assert lot.lot_id == 42
    assert lot.make == "Mazda"
    assert lot.model == "6"
    assert lot.link is None
    assert lot.link_img_hd is None
    assert lot.link_img_small is None
