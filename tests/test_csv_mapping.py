"""Tests for CSV mapping loader."""

import textwrap

import pytest

from neo4j_ingest.csv_mapping import load_csv_mapping


def _write_csv(tmp_path, content):
    p = tmp_path / "mapping.csv"
    p.write_text(textwrap.dedent(content))
    return p


class TestLoadCsvMapping:
    def test_basic_node_mapping(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            employees,1:1,emp_id,int,true,,Person,emp_id,,,
            employees,1:1,full_name,string,false,strip,Person,name,,,
            employees,1:1,email,string,false,lowercase,Person,email,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)

        assert len(cfg.nodes) == 1
        node = cfg.nodes[0]
        assert node.label == "Person"
        assert node.key == "emp_id"
        assert node.source == "employees"
        assert len(node.properties) == 3

        # Check property names
        prop_targets = [p.target_name for p in node.properties]
        assert "emp_id" in prop_targets
        assert "name" in prop_targets
        assert "email" in prop_targets

    def test_data_type_generates_transform(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            src,1:1,id,int,true,,Node,id,,,
            src,1:1,score,float,false,,Node,score,,,
            src,1:1,active,bool,false,,Node,active,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)

        node = cfg.nodes[0]
        # id should have to_int transform
        id_prop = next(p for p in node.properties if p.target_name == "id")
        assert id_prop.transform is not None
        assert id_prop.transform[0].type == "to_int"

        # score should have to_float transform
        score_prop = next(p for p in node.properties if p.target_name == "score")
        assert score_prop.transform[0].type == "to_float"

        # active should have to_bool transform
        active_prop = next(p for p in node.properties if p.target_name == "active")
        assert active_prop.transform[0].type == "to_bool"

    def test_chained_transforms(self, tmp_path):
        """data_type + explicit transform should chain."""
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            src,1:1,name,string,false,"strip,uppercase",Node,name,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)
        prop = cfg.nodes[0].properties[0]
        assert prop.transform is not None
        assert len(prop.transform) == 2
        assert prop.transform[0].type == "strip"
        assert prop.transform[1].type == "uppercase"

    def test_relationship_mapping(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            employees,1:1,emp_id,int,true,,Person,emp_id,,,
            employees,1:M,dept_id,int,false,,Department,dept_id,WORKS_IN,emp_id,dept_id
        """)
        cfg = load_csv_mapping(p, auto_schema=False)

        assert len(cfg.relationships) == 1
        rel = cfg.relationships[0]
        assert rel.rel_type == "WORKS_IN"
        assert rel.from_label == "employees"
        assert rel.to_label == "Department"
        assert rel.source == "employees"

    def test_auto_generated_relationship_type(self, tmp_path):
        """When relationship_type is empty, auto-generate from entities."""
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            orders,1:1,order_id,int,true,,Order,order_id,,,
            orders,1:M,product_id,int,false,,Product,product_id,,order_id,product_id
        """)
        cfg = load_csv_mapping(p, auto_schema=False)
        rel = cfg.relationships[0]
        assert rel.rel_type == "HAS_PRODUCT"

    def test_multiple_source_entities(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            employees,1:1,emp_id,int,true,,Person,emp_id,,,
            employees,1:1,name,string,false,,Person,name,,,
            departments,1:1,dept_id,int,true,,Department,dept_id,,,
            departments,1:1,dept_name,string,false,,Department,name,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)

        assert len(cfg.nodes) == 2
        labels = {n.label for n in cfg.nodes}
        assert labels == {"Person", "Department"}

    def test_auto_schema_generates_constraints(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            employees,1:1,emp_id,int,true,,Person,emp_id,,,
            departments,1:1,dept_id,int,true,,Department,dept_id,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=True)

        assert cfg.graph_schema is not None
        assert len(cfg.graph_schema.constraints) == 2

        labels = {c.label for c in cfg.graph_schema.constraints}
        assert labels == {"Person", "Department"}
        assert all(c.type == "unique" for c in cfg.graph_schema.constraints)

    def test_stub_sources_generated_when_none_provided(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            employees,1:1,emp_id,int,true,,Person,emp_id,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)

        assert len(cfg.sources) == 1
        assert cfg.sources[0].name == "employees"
        assert cfg.sources[0].type == "csv"

    def test_explicit_sources_used_when_provided(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            mydata,1:1,id,int,true,,Thing,id,,,
        """)
        sources = [{"name": "mydata", "type": "csv", "path": "/data/my.csv"}]
        cfg = load_csv_mapping(p, sources=sources, auto_schema=False)

        assert cfg.sources[0].path == "/data/my.csv"

    def test_skips_rows_with_empty_source(self, tmp_path):
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            employees,1:1,emp_id,int,true,,Person,emp_id,,,
            ,1:1,orphan,string,false,,Person,orphan,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)

        # The empty-source row should be skipped
        assert len(cfg.nodes) == 1
        assert len(cfg.nodes[0].properties) == 1

    def test_target_defaults_to_source_column(self, tmp_path):
        """When target_column is empty, it defaults to source_column."""
        p = _write_csv(tmp_path, """\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            src,1:1,my_field,string,true,,Node,,,,
        """)
        cfg = load_csv_mapping(p, auto_schema=False)
        prop = cfg.nodes[0].properties[0]
        assert prop.target_name == "my_field"

    def test_load_config_routes_csv(self, tmp_path):
        """load_config should auto-detect .csv and use the CSV mapping loader."""
        from neo4j_ingest.config import load_config

        p = tmp_path / "mapping.csv"
        p.write_text(textwrap.dedent("""\
            source_entity,field_cardinality,source_column,data_type,is_key,transform,target_entity,target_column,relationship_type,rel_source_key,rel_target_key
            src,1:1,id,int,true,,Node,id,,,
        """))

        cfg = load_config(p)
        assert len(cfg.nodes) == 1
        assert cfg.nodes[0].label == "Node"
