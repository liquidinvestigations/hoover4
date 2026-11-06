"""Rewrite historical NER completion and verify its searchable publication."""

import json
from dataclasses import dataclass, field

from temporalio import activity
from tasks.P4_extract_entities.completion import NER_STAGE_VERSION
from tasks.heartbeat import with_heartbeat, stop_if_worker_is_stopping


@dataclass
class EntityUpdateParams:
    collectionname: str
    collection_dataset: str
    op_id: str = ""
    hashes: list[str] = field(default_factory=list)
    after: str = ""
    done: int = 0


def contract(target=None):
    from tasks.P4_extract_entities.completion import target as current_target
    from .registry import STEPS_BY_ID, fingerprint
    return fingerprint(STEPS_BY_ID["entities"], json.dumps(target or current_target(), sort_keys=True))


def identity_sql(alias="n"):
    return f"concat({alias}.nlp_model, ':', {alias}.extracted_by, ':', toString({alias}.page_id), ':', toString({alias}.text_version), ':', {alias}.text_digest)"


def pending_sql(target):
    sql = (
        "SELECT DISTINCT t.file_hash AS hash FROM ("
        "SELECT file_hash, extracted_by, page_id, max(version) AS text_version, "
        "lower(hex(SHA256(argMax(text, version)))) AS text_digest FROM text_content "
        "WHERE collection_dataset = {cd:String} GROUP BY file_hash, extracted_by, page_id) AS t "
        "LEFT JOIN (SELECT * FROM nlp_processed FINAL WHERE collection_dataset = {cd:String} "
        "AND nlp_model = {ner_model:String}) AS n ON t.file_hash = n.file_hash "
        "AND t.extracted_by = n.extracted_by AND t.page_id = n.page_id "
        "WHERE t.file_hash IN (SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0) "
        f"AND (n.stage_version != {NER_STAGE_VERSION} OR n.text_version != t.text_version OR n.text_digest != t.text_digest "
        "OR (n.file_hash,n.extracted_by,n.page_id,n.nlp_model) NOT IN ("
        "SELECT file_hash,extracted_by,page_id,nlp_model FROM entity_hit FINAL "
        "WHERE collection_dataset = {cd:String} GROUP BY file_hash,extracted_by,page_id,nlp_model "
        "HAVING uniqExact(entity_type) = 4) "
        f"OR (n.file_hash, {identity_sql()}) NOT IN (SELECT file_hash, output_identity FROM processing_output_receipts "
        "WHERE collection_dataset = {cd:String} AND output_kind = 'entities' "
        "AND fingerprint = {ner_contract:String} AND stage = 'search'))")
    return sql, {"ner_model": target["model"], "ner_contract": contract(target)}


@activity.defn
@with_heartbeat
def list_entity_update_hashes(params: EntityUpdateParams) -> list[str]:
    from database.clickhouse import get_collection_client
    from tasks.P4_extract_entities.completion import target
    wanted = target()
    if not wanted["enabled"]:
        return []
    sql, values = pending_sql(wanted)
    with get_collection_client(params.collectionname) as client:
        rows = client.query(f"SELECT hash FROM ({sql}) WHERE hash > {{after:String}} ORDER BY hash LIMIT 100",
            parameters={**values, "cd": params.collection_dataset, "after": params.after}).result_rows
    return [row[0] for row in rows]


def completions(client, params):
    from tasks.P4_extract_entities.completion import target
    wanted = target()
    rows = client.query(
        "SELECT n.file_hash,n.extracted_by,n.page_id,n.text_version,n.text_digest,n.nlp_model FROM nlp_processed AS n FINAL "
        "INNER JOIN (SELECT file_hash,extracted_by,page_id,max(version) AS v,lower(hex(SHA256(argMax(text,version)))) AS d "
        "FROM text_content WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
        "GROUP BY file_hash,extracted_by,page_id) AS t ON n.file_hash=t.file_hash AND n.extracted_by=t.extracted_by AND n.page_id=t.page_id "
        "WHERE n.collection_dataset = {cd:String} AND n.file_hash IN {hashes:Array(String)} "
        "AND n.nlp_model = {model:String} AND n.stage_version = {ner_version:UInt16} AND n.text_version=t.v AND n.text_digest=t.d",
        parameters={"cd": params.collection_dataset, "hashes": params.hashes, "model": wanted["model"], "ner_version": NER_STAGE_VERSION}).result_rows
    expected = client.query("SELECT DISTINCT file_hash,extracted_by,page_id FROM text_content WHERE collection_dataset={cd:String} "
        "AND file_hash IN {hashes:Array(String)}", parameters={"cd": params.collection_dataset, "hashes": params.hashes}).result_rows
    if {tuple(row[:3]) for row in rows} != set(expected):
        raise RuntimeError("NER has incomplete current provider output")
    return rows


def verify_index(params):
    from database.clickhouse import get_collection_client
    from database.manticore import get_manticore_client, shard_table_from_name
    from tasks.P6_index_data.activities import union_entities_by_segment, pages_row_id
    from tasks.P6_index_data.string_term_encodings import fetch_string_term_ids
    from tasks.P6_index_data.location_refresh import parse_mva_ids
    from tasks.entity_stoplist import filter_entity_values
    with get_collection_client(params.collectionname) as client:
        completions(client, params)
        rows = client.query_arrow("SELECT file_hash,extracted_by,page_id,entity_type,entity_values FROM entity_hit FINAL "
            "WHERE collection_dataset={cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd":params.collection_dataset,"hashes":params.hashes}).to_pylist()
        entities = union_entities_by_segment(rows)
        pages = client.query("SELECT DISTINCT file_hash,extracted_by,page_id FROM text_content "
            "WHERE collection_dataset={cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd":params.collection_dataset,"hashes":params.hashes}).result_rows
        assignments = dict(client.query("SELECT file_hash,shard_name FROM manticore_shard_assignments FINAL "
            "WHERE collection_dataset={cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd":params.collection_dataset,"hashes":params.hashes}).result_rows)
    values = {value for page in entities.values() for group in page.values() for value in filter_entity_values(group)}
    ids = fetch_string_term_ids(params.collectionname, params.collection_dataset, "ner", values)
    if set(ids) != values:
        raise RuntimeError("NER term dictionary is incomplete")
    expected = {}
    for file_hash, source, page in pages:
        groups = entities.get((file_hash,source,page), {})
        expected[pages_row_id(params.collection_dataset,file_hash,source,int(page))] = tuple(
            frozenset(ids[value] for value in filter_entity_values(groups.get(kind, []))) for kind in ("PER","ORG","LOC","MISC"))
    actual = {}
    with get_manticore_client() as connection:
        for shard in sorted(set(assignments.values())):
            hashes = [h for h,s in assignments.items() if s == shard]
            last = 0
            while True:
                stop_if_worker_is_stopping()
                cur = connection.cursor()
                cur.execute(f"SELECT id,ner_per,ner_org,ner_loc,ner_misc FROM {shard_table_from_name(shard)} "
                    f"WHERE collection_dataset=%s AND file_hash IN ({','.join(['%s']*len(hashes))}) "
                    "AND extracted_by != 'filename_index' AND id > %s ORDER BY id ASC LIMIT 1000 OPTION max_matches=1000",
                    (params.collection_dataset,*hashes,last))
                page = cur.fetchall() or []
                for row in page:
                    actual[int(row[0])] = tuple(parse_mva_ids(value) for value in row[1:])
                    last = int(row[0])
                if len(page) < 1000:
                    break
    if actual != expected:
        raise RuntimeError("NER search attributes are incomplete or stale")
    from .selectors import ScopeContext, missing_search_terms
    with get_collection_client(params.collectionname) as client:
        if missing_search_terms(client, ScopeContext("dataset",params.collection_dataset,params.collectionname)):
            raise RuntimeError("NER searchable terms are incomplete")


def rewrite_ner_attributes(params, assignments):
    """Replace NER attributes while preserving stored text and every other search attribute."""
    from database.clickhouse import get_collection_client
    from database.manticore import get_manticore_client, shard_table_from_name, manticore_execute, limit_encoded_runs
    from tasks.P6_index_data.activities import union_entities_by_segment, pages_replace_sql, pages_replace_params, _MVA_COLUMNS, _OCR_MVA_COLUMNS, repr_manticore_tuple
    from tasks.P6_index_data.string_term_encodings import get_string_term_ids
    from tasks.P6_index_data.location_refresh import parse_mva_ids
    from tasks.text_sources import fetch_text_batch
    from tasks.plan_utils import clean_text
    from tasks.entity_stoplist import filter_entity_values
    with get_collection_client(params.collectionname) as client:
        groups = union_entities_by_segment(client.query_arrow(
            "SELECT file_hash,extracted_by,page_id,entity_type,entity_values FROM entity_hit FINAL "
            "WHERE collection_dataset={cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd":params.collection_dataset,"hashes":params.hashes}).to_pylist())
    values = {value for page in groups.values() for group in page.values() for value in filter_entity_values(group)}
    ids = get_string_term_ids(params.collectionname,params.collection_dataset,"ner",values)
    with get_manticore_client() as connection:
        for shard in sorted(set(assignments.values())):
            table = shard_table_from_name(shard)
            hashes = [h for h,s in assignments.items() if s==shard]
            last = 0
            while True:
                stop_if_worker_is_stopping()
                cur = connection.cursor()
                cur.execute(f"SELECT * FROM {table} WHERE collection_dataset=%s "
                    f"AND file_hash IN ({','.join(['%s']*len(hashes))}) AND extracted_by != 'filename_index' "
                    "AND id>%s ORDER BY id ASC LIMIT 32 OPTION max_matches=32",(params.collection_dataset,*hashes,last))
                rows = [dict(zip(cur.column_names,row)) for row in cur.fetchall()]
                if not rows:
                    break
                keys = [(row["file_hash"],row["extracted_by"],int(row["page_id"])) for row in rows]
                with get_collection_client(params.collectionname) as client:
                    bodies = { (row["file_hash"],row["extracted_by"],int(row["page_id"])): row["text"]
                               for row in fetch_text_batch(client,params.collection_dataset,keys) }
                for row,key in zip(rows,keys):
                    if key not in bodies or row["page_text"] != limit_encoded_runs(clean_text(bodies[key])):
                        raise RuntimeError("NER update awaits current indexed source text")
                    last = int(row["id"])
                    for column in _MVA_COLUMNS+_OCR_MVA_COLUMNS:
                        if column in row:
                            row[column] = repr_manticore_tuple(sorted(parse_mva_ids(row[column])))
                    for kind in ("PER","ORG","LOC","MISC"):
                        row[f"ner_{kind.lower()}"] = repr_manticore_tuple(sorted({ids[value] for value in filter_entity_values(groups.get(key,{}).get(kind,[]))}))
                    manticore_execute(connection,pages_replace_sql(table,row),pages_replace_params(params.collection_dataset,row))
                connection.commit()
                if len(rows)<32:
                    break


@activity.defn
@with_heartbeat
def finish_entity_update(params: EntityUpdateParams) -> None:
    from database.clickhouse import get_collection_client, insert_durable
    from tasks.P6_index_data.activities import index_entity_terms
    from tasks.P6_index_data.params import BuildVfsNodesParams
    with get_collection_client(params.collectionname) as client:
        before = completions(client, params)
        assignments = dict(client.query("SELECT file_hash,shard_name FROM manticore_shard_assignments FINAL "
            "WHERE collection_dataset={cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd":params.collection_dataset,"hashes":params.hashes}).result_rows)
        if set(assignments) != set(params.hashes):
            raise RuntimeError("NER update awaits document index assignment")
        # Retain terms referenced by every other provider and variant of this dataset.
        for table in ("string_term_id_to_text", "string_term_text_to_id"):
            client.command(f"DELETE FROM {table} WHERE collection_dataset={{cd:String}} AND term_field='ner' "
                "AND term_value NOT IN (SELECT arrayJoin(entity_values) FROM entity_hit FINAL WHERE collection_dataset={cd:String}) "
                "SETTINGS mutations_sync=2", parameters={"cd":params.collection_dataset})
    rewrite_ner_attributes(params, assignments)
    index_entity_terms(BuildVfsNodesParams(params.collectionname, params.collection_dataset))
    verify_index(params)
    with get_collection_client(params.collectionname) as client:
        after = completions(client, params)
        if sorted(after) != sorted(before):
            raise RuntimeError("NER completion changed during indexing")
        insert_durable(client, "processing_output_receipts", [
            [params.collection_dataset,h,"entities",f"{model}:{source}:{page}:{version}:{digest}",contract(),"search",params.op_id]
            for h,source,page,version,digest,model in after],
            column_names=["collection_dataset","file_hash","output_kind","output_identity","fingerprint","stage","op_id"])
