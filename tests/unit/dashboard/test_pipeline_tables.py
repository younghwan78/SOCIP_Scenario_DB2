from dashboard.components.pipeline_tables import dma_rows, dma_summary, estimate_frame_bytes, transform_rows


def _view():
    return {
        "nodes": [
            {"data": {"id": "mlsc", "label": "MLSC", "type": "ip", "dma_count": 6,
                      "active_operations": {"scale": False, "crop": False}, "capability_badges": ["crop", "scale"]}},
            {"data": {"id": "mcsc", "label": "MCSC", "type": "ip",
                      "active_operations": {"scale": True, "scale_ratio": 0.94, "crop": True,
                                            "scale_from": "4080x2296", "scale_to": "3840x2160"}}},
            {"data": {"id": "mtnr", "label": "MTNR", "type": "ip"}},
            {"data": {"id": "buf_PYRAMID_L1", "label": "Pyramid L1", "type": "buffer",
                      "memory": {"format": "YUV444", "bitdepth": 12, "width": 2040, "height": 1148,
                                 "compression": "COMP_OFF"}}},
        ],
        "edges": [
            {"data": {"id": "e1", "source": "mlsc", "target": "buf_PYRAMID_L1", "flow_type": "M2M",
                      "buffer_ref": "PYRAMID_L1", "producer": "mlsc", "consumer": "mtnr",
                      "port_pairs": [{"src": "MLSC_W_GLPG1_Y", "dst": "MTNR1_RDMA_CUR_L1_Y"}]}},
            {"data": {"id": "e2", "source": "buf_PYRAMID_L1", "target": "mtnr", "flow_type": "M2M",
                      "buffer_ref": "PYRAMID_L1", "producer": "mlsc", "consumer": "mtnr"}},
            {"data": {"id": "e3", "source": "mlsc", "target": "mtnr", "flow_type": "OTF"}},
            {"data": {"id": "e4", "source": "mcsc", "target": "mtnr", "flow_type": "M2M", "buffer_ref": "NOSIZE"}},
        ],
    }


def test_dma_rows_dedupe_buffer_hops_and_keep_ports_and_memory():
    rows = dma_rows(_view())
    assert len(rows) == 2
    pyramid = next(row for row in rows if row["Buffer"] == "PYRAMID_L1")
    assert pyramid["Producer"] == "MLSC" and pyramid["Consumer"] == "MTNR"
    assert pyramid["WDMA port"] == "MLSC_W_GLPG1_Y"
    assert pyramid["RDMA port"] == "MTNR1_RDMA_CUR_L1_Y"
    assert pyramid["Size"] == "2040x1148" and pyramid["Bit"] == 12
    assert pyramid["Frame MB (est.)"] == round(2040 * 1148 * 3 * 2 / 1048576, 2)
    nosize = next(row for row in rows if row["Buffer"] == "NOSIZE")
    assert nosize["Size source"] == "size 미정의"
    summary = dma_summary(rows)
    assert summary["transfers"] == 2 and summary["missing_size"] == 1


def test_estimate_frame_bytes_prefers_declared_size():
    assert estimate_frame_bytes({"size_bytes": 10, "width": 1, "height": 1, "format": "Y"}) == 10
    assert estimate_frame_bytes({"width": 1920, "height": 1080, "format": "YUV420", "bitdepth": 8}) == 3110400
    assert estimate_frame_bytes({"width": 10, "height": 10, "format": "BITSTREAM"}) is None


def test_transform_rows_orders_active_before_bypass():
    rows = transform_rows(_view())
    assert [row["IP / node"] for row in rows] == ["MCSC", "MLSC"]
    assert rows[0]["Active ops"] == "scale ×0.94, crop"
    assert rows[0]["Out"] == "3840x2160"
    assert rows[1]["Active ops"] == "bypass" and rows[1]["Capability"] == "crop, scale"
