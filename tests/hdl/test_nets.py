"""Ports, signals, buses, slices, concatenations and open pins."""

import pytest

import spicule.hdl as h
import spicule.ir as ir


def test_scalar_and_bus_shapes():
    assert h.Port().width == 1
    assert h.Port().range is None
    d = h.Port(width=8)
    assert (d.range, d.width) == (ir.Range(msb=7, lsb=0), 8)
    r = h.Signal(msb=0, lsb=3)
    assert (r.range, r.width) == (ir.Range(msb=0, lsb=3), 4)


@pytest.mark.parametrize(
    "kwargs",
    [{"width": 0}, {"width": True}, {"width": 2, "msb": 1, "lsb": 0}, {"msb": 3}, {"msb": -1, "lsb": 0}],
)
def test_bad_shapes(kwargs):
    with pytest.raises(h.HdlError):
        h.Port(**kwargs)


def test_indexing_uses_bit_names():
    d = h.Port(msb=7, lsb=4)
    assert d[5].range == ir.Range(msb=5, lsb=5)
    assert (d[7:6].range, d[7:6].width) == (ir.Range(msb=7, lsb=6), 2)
    reverse = d[4:7]
    assert reverse.range == ir.Range(msb=4, lsb=7)
    inner = reverse[5:6]
    assert (inner.net, inner.range) == (d, ir.Range(msb=5, lsb=6))


@pytest.mark.parametrize("key", [3, 8, slice(7, None), slice(None, 4), slice(7, 4, 1), "a", True])
def test_bad_indices(key):
    with pytest.raises(h.HdlError):
        h.Port(msb=7, lsb=4)[key]


def test_scalar_cannot_be_indexed():
    with pytest.raises(h.HdlError, match="scalar"):
        h.Port()[0]


def test_concat_flattens_and_needs_widths():
    a, b = h.Port(width=4), h.Port()
    c = h.Concat(a[3:2], h.Concat(b, h.NoConn(2)))
    assert c.width == 5
    assert len(c.parts) == 3
    with pytest.raises(h.HdlError, match="explicit width"):
        h.Concat(a, h.NoConn())
    with pytest.raises(h.HdlError, match="empty"):
        h.Concat()
    with pytest.raises(h.HdlError, match="not connectable"):
        h.Concat(a, "b")  # ty: ignore[invalid-argument-type]


def test_noconn_width():
    assert h.NoConn().width is None
    assert h.NoConn(3).width == 3
    with pytest.raises(h.HdlError):
        h.NoConn(0)


def test_errors_point_at_the_caller():
    with pytest.raises(h.HdlError) as error:
        h.Port(width=0)
    assert error.value.sources[0].file == __file__


def test_a_bus_unpacks_into_its_bits():
    d = h.Signal(msb=3, lsb=0)
    assert [bit.range for bit in d] == [ir.Range(msb=i, lsb=i) for i in (3, 2, 1, 0)]
    assert [bit.range for bit in d[0:2]] == [ir.Range(msb=i, lsb=i) for i in (0, 1, 2)]
    with pytest.raises(h.HdlError, match="can't be iterated"):
        list(h.Signal())
    with pytest.raises(h.HdlError, match="can't be iterated"):
        list(h.NoConn(2))
    with pytest.raises(h.HdlError, match="can't be iterated"):
        list(h.Concat(d[3], d[2]))


def test_several_nets_at_once():
    a, y = h.Ports(2)
    assert isinstance(a, h.Port) and a is not y
    d, q = h.Signals(2, width=4)
    assert isinstance(q, h.Signal) and (d.width, q.width) == (4, 4)
    for bad in (0, True, "2"):
        with pytest.raises(h.HdlError, match="number of nets"):
            h.Ports(bad)  # ty: ignore[invalid-argument-type]


def test_nested_tuples_concatenate():
    a = h.Signal()
    d = h.Signal(width=4)
    assert h.Concat(a, (d[3:2], a)).width == 4


def test_a_slice_checks_itself():
    d = h.Signal(msb=7, lsb=4)
    s = h.Slice(d, 6, 5)
    assert (s.range, s.width) == (ir.Range(msb=6, lsb=5), 2)
    with pytest.raises(h.HdlError, match=r"outside 4\.\.7"):
        h.Slice(d, 3, 2)
    with pytest.raises(h.HdlError, match="ints >= 0"):
        h.Slice(d, -1, 4)
    with pytest.raises(h.HdlError, match="scalar"):
        h.Slice(h.Signal(), 0, 0)


def test_a_slice_of_a_slice_stays_inside_it():
    d = h.Signal(width=8)
    assert repr(d[7:4][6:5]) == "?<6:5>"
    with pytest.raises(h.HdlError, match=r"outside 4\.\.7"):
        d[7:4][3:2]
