"""Create isolated documents for browser verification."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from database import clickhouse, manticore
from tasks.plan_utils import clean_text
from tasks.P3_parse_files import parse_table, table_generations

from datetime import datetime, timezone
from database import clickhouse, manticore
from database.s3 import get_s3_client, collection_bucket

clickhouse.clickhouse_migrate()
name = 'release_browser'
clickhouse.migrate_collection(name)
now = datetime.now(timezone.utc).replace(tzinfo=None)
with clickhouse.get_global_client() as client:
    exists = client.query('SELECT count() FROM collections FINAL WHERE collectionname = {name:String}', parameters={'name':name}).result_rows[0][0]
    if not exists:
        clickhouse.insert_durable(client, 'collections', [[name, 'Release browser fixtures', 1]], column_names=['collectionname','fullname','is_public'])
    for slug, label in [('primary','Primary documents'),('duplicate','Duplicate documents'),('disposable','Delete this dataset')]:
        dataset = name + '_' + slug
        exists = client.query('SELECT count() FROM dataset FINAL WHERE collection_dataset = {dataset:String}', parameters={'dataset':dataset}).result_rows[0][0]
        if not exists:
            clickhouse.insert_durable(client,'dataset',[[dataset,name,slug,label,'s3','fixtures/',None,'admin',now,now]],column_names=['collection_dataset','collectionname','dataset_name','dataset_display_name','dataset_type','dataset_path','dataset_access_json','user_id','date_created','date_modified'])
manticore.create_shard_tables(name,1)
manticore.create_entities_table(name)
manticore.create_vfs_table(name)
storage = get_s3_client()
bucket = collection_bucket(name)
if not storage.bucket_exists(bucket):
    storage.make_bucket(bucket)
print('Browser fixture schema, registry, indexes, and bucket are ready.')

collection = 'release_browser'
datasets = ['release_browser_primary', 'release_browser_duplicate']
now = datetime(2026, 1, 1)
manifest = {'collection': collection, 'datasets': datasets, 'documents': {}}
with clickhouse.get_collection_client(collection) as client:
    def insert(table, row):
        clickhouse.insert_durable(client, table, [list(row.values())], column_names=list(row))
    def base(dataset, name, source, kind, mime):
        raw = source.encode()
        h = hashlib.sha3_256(raw).hexdigest()
        insert('blobs', dict(collection_dataset=dataset, blob_hash=h, blob_size_bytes=len(raw), stored_in_clickhouse=1))
        insert('blob_values', dict(collection_dataset=dataset, blob_hash=h, blob_length=len(raw), blob_value=source))
        insert('vfs_files', dict(collection_dataset=dataset, container_hash='', path='/'+name, hash=h, file_size_bytes=len(raw), updated_at=now))
        insert('file_types', dict(collection_dataset=dataset, hash=h, extracted_by='fixture', mime_type=[mime], mime_encoding=['utf-8'], file_type=[kind], extensions=[name.rsplit('.',1)[-1]]))
        insert('file_type_canonical', dict(collection_dataset=dataset, hash=h, file_type=kind))
        return h
    def text(dataset,h,source,extractor,index):
        indexed = manticore.limit_encoded_runs(clean_text(source))
        insert('text_content',dict(collection_dataset=dataset,file_hash=h,extracted_by=extractor,page_id=1,text=source,text_bytes=len(source.encode()),version=1))
        insert('manticore_shard_assignments',dict(collection_dataset=dataset,file_hash=h,shard_name=collection+'_1',text_bytes=len(indexed.encode())))
        with manticore.get_manticore_client() as connection:
            cursor=connection.cursor()
            cursor.execute('REPLACE INTO release_browser_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id) VALUES (%s,%s,%s,%s,%s,1)',(index,indexed,h,dataset,extractor))
        return indexed
    source = '  quokka café\r\n' + 'A'*240 + '\r\nquokka harbor quokka forest quokka  '
    h=base(datasets[0],'projected-source.txt',source,'text','text/plain')
    text(datasets[0],h,source,'raw_text',790001)
    manifest['documents']['projection']={'collection_dataset':datasets[0],'file_hash':h,'find_query':'quokka','expected_body_matches':4}
    for n,subject in enumerate(['quokka shared message','Reply to shared message']):
        source='From: Sender <sender@example.invalid>\nSubject: '+subject+'\n\nquokka harbor quokka forest.\n'
        target_datasets=datasets if n==0 else datasets[:1]
        for j,dataset in enumerate(target_datasets):
            h=base(dataset, 'shared.eml' if n==0 else 'reply.eml',source,'email','message/rfc822')
            insert('emails',dict(collection_dataset=dataset,email_hash=h,email_type='eml'))
            insert('email_headers',dict(collection_dataset=dataset,email_hash=h,subject=subject,addresses='quokka',raw_headers_json=json.dumps({'Subject':subject}),date_sent=now,date_sent_known=1))
            for role,address,display in [('from','sender@example.invalid','Sender'),('to','first@example.invalid','quokka'),('to','second@example.invalid','quokka'),('cc','first@example.invalid','quokka')]:
                insert('email_addresses',dict(collection_dataset=dataset,email_hash=h,role=role,address=address,display_name=display,updated_at=now))
            text(dataset,h,'quokka harbor quokka forest.\n','email_parser',790010+n*10+j)
        manifest['documents']['email' if n==0 else 'reply']={'collection_dataset':datasets[0],'file_hash':h,'find_query':'quokka'}
    root=manifest['documents']['email']['file_hash']
    child=manifest['documents']['reply']['file_hash']
    insert('email_edges',dict(collectionname=collection,src_dataset=datasets[0],src_hash=root,dst_dataset=datasets[0],dst_hash=child,kind='reply',confidence=0.9,evidence='fixture reply'))
    table_generations.send_command=table_generations.apply_table_generation_command
    for n in range(2):
        source='Name,Count,Description\n'+''.join(f'row-{n}-{i},{i},quokka record {i}\n' for i in range(1,121))
        name=f'table-{n}.csv'
        h=base(datasets[0],name,source,'table','text/csv')
        path=Path('/tmp')/name
        path.write_text(source)
        result=parse_table.parse_table_and_store(parse_table.ParseTableParams(collection,datasets[0],h,str(path),900,mime_types=['text/csv'],file_names=[name]))
        assert result['status']=='ok',result
        text(datasets[0],h,source,'table_text',790030+n)
        manifest['documents'][f'table_{n}']={'collection_dataset':datasets[0],'file_hash':h,'find_query':'quokka'}
    insert('manticore_shards',dict(shard_name=collection+'_1',shard_index=1,text_bytes=10000,doc_count=6))
print(json.dumps(manifest,indent=2))

from database import clickhouse,manticore
from tasks.plan_utils import clean_text
with clickhouse.get_collection_client('release_browser') as client:
    for dataset in ['release_browser_primary','release_browser_duplicate']:
        for field,identifier,value in [('language',790101,'de'),('filetype',790102,'text'),('ocr_language',790103,'de'),('ocr_script',790104,'Latin')]:
            clickhouse.insert_durable(client,'string_term_id_to_text',[[dataset,field,identifier,value]],column_names=['collection_dataset','term_field','term_id','term_value'])
    h,source=client.query("SELECT file_hash,argMax(text,version) FROM text_content WHERE collection_dataset='release_browser_primary' AND extracted_by='raw_text' GROUP BY file_hash LIMIT 1").result_rows[0]
with manticore.get_manticore_client() as connection:
    cursor=connection.cursor()
    cursor.execute("REPLACE INTO release_browser_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,language,file_types,ocr_language,ocr_script,file_size_bytes) VALUES (790001,%s,%s,'release_browser_primary','raw_text',1,(790101),(790102),(790103),(790104),500)",(manticore.limit_encoded_runs(clean_text(source)),h))
    cursor.execute('SELECT id,language,file_types,ocr_language,ocr_script,file_size_bytes FROM release_browser_1_pages WHERE id=790001')
    print(cursor.fetchall())

import hashlib,json
from database import clickhouse,manticore
from tasks.P6_index_data.activities import build_vfs_nodes,index_vfs_structure,index_entity_terms
from tasks.P6_index_data.params import BuildVfsNodesParams
collection='release_browser'
dataset='release_browser_primary'
source='Synthetic stored mail archive fixture.'
h=hashlib.sha3_256(source.encode()).hexdigest()
with clickhouse.get_collection_client(collection) as client:
    def insert(table,row):
        clickhouse.insert_durable(client,table,[list(row.values())],column_names=list(row))
    insert('blobs',dict(collection_dataset=dataset,blob_hash=h,blob_size_bytes=len(source),stored_in_clickhouse=1))
    insert('blob_values',dict(collection_dataset=dataset,blob_hash=h,blob_length=len(source),blob_value=source))
    insert('vfs_files',dict(collection_dataset=dataset,container_hash='',path='/mail-store.pst',hash=h,file_size_bytes=len(source)))
    insert('file_type_canonical',dict(collection_dataset=dataset,hash=h,file_type='archive',mime_type='application/x-hoover-pst'))
    insert('archives',dict(collection_dataset=dataset,archive_hash=h,archive_type='application/x-hoover-pst'))
    email=client.query("SELECT email_hash FROM email_headers FINAL WHERE collection_dataset={dataset:String} AND subject='quokka shared message'",parameters={'dataset':dataset}).result_rows[0][0]
    insert('vfs_files',dict(collection_dataset=dataset,container_hash=h,path='/member.eml',hash=email,file_size_bytes=100))
params=BuildVfsNodesParams(collection,dataset)
print(build_vfs_nodes(params))
print(index_vfs_structure(params))
print(index_entity_terms(params))
with clickhouse.get_collection_client(collection) as client:
    key=client.query("SELECT node_key FROM vfs_nodes FINAL WHERE collection_dataset={dataset:String} AND file_hash={hash:String} AND kind='container'",parameters={'dataset':dataset,'hash':h}).result_rows[0][0]
    term=client.query("SELECT term_id FROM string_term_id_to_text FINAL WHERE collection_dataset={dataset:String} AND term_field='vfs_node' AND term_value={key:String}",parameters={'dataset':dataset,'key':key}).result_rows[0][0]
with manticore.get_manticore_client() as connection:
    cursor=connection.cursor()
    cursor.execute("REPLACE INTO release_browser_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,file_paths) VALUES (790010,%s,%s,%s,'email_parser',1,(%s))",('quokka harbor quokka forest.',email,dataset,term))
print(json.dumps({'collection_dataset':dataset,'file_hash':h,'folder_term_id':term,'member_hash':email}))

# The second email has another body source for source-switch navigation.
with clickhouse.get_collection_client(collection) as client:
    reply = client.query("SELECT email_hash FROM email_headers FINAL WHERE collection_dataset={dataset:String} AND subject='Reply to shared message'", parameters={'dataset': dataset}).result_rows[0][0]
    body = 'quokka harbor quokka forest.\n'
    clickhouse.insert_durable(client, 'text_content', [[dataset, reply, 'raw_text', 1, body, len(body.encode()), 1]], column_names=['collection_dataset', 'file_hash', 'extracted_by', 'page_id', 'text', 'text_bytes', 'version'])
with manticore.get_manticore_client() as connection:
    connection.cursor().execute("REPLACE INTO release_browser_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id) VALUES (790040,%s,%s,%s,'raw_text',1)", (body, reply, dataset))

# SQLite supplies two real sheets through the production table reader.
import sqlite3
from tempfile import TemporaryDirectory
with TemporaryDirectory() as directory:
    path = Path(directory) / 'multiple.sqlite'
    with sqlite3.connect(path) as connection:
        for sheet, prefix in [('First', 'sheet-one-'), ('Second', 'sheet-two-')]:
            connection.execute(f'CREATE TABLE {sheet} (Name TEXT, Count INTEGER, Description TEXT)')
            connection.executemany(f'INSERT INTO {sheet} VALUES (?,?,?)', [(f'{prefix}{i}', i, f'quokka record {i}') for i in range(1, 121)])
    raw = path.read_bytes()
    multi_hash = hashlib.sha3_256(raw).hexdigest()
    with clickhouse.get_collection_client(collection) as client:
        def put(table, row):
            clickhouse.insert_durable(client, table, [list(row.values())], column_names=list(row))
        put('blobs', dict(collection_dataset=dataset, blob_hash=multi_hash, blob_size_bytes=len(raw), stored_in_clickhouse=1))
        put('blob_values', dict(collection_dataset=dataset, blob_hash=multi_hash, blob_length=len(raw), blob_value=raw))
        put('vfs_files', dict(collection_dataset=dataset, container_hash='', path='/multiple.sqlite', hash=multi_hash, file_size_bytes=len(raw)))
        put('file_type_canonical', dict(collection_dataset=dataset, hash=multi_hash, file_type='table'))
    result = parse_table.parse_table_and_store(parse_table.ParseTableParams(collection, dataset, multi_hash, str(path), 900, mime_types=['application/x-sqlite3'], file_names=['multiple.sqlite']))
    assert result['status'] == 'ok', result
print(json.dumps({'table_multi': {'collection_dataset': dataset, 'file_hash': multi_hash}, 'reply_sources': ['email_parser', 'raw_text']}))
print(build_vfs_nodes(params))
print(index_vfs_structure(params))
print(index_entity_terms(params))
