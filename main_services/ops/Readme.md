# Ops

## Docker

The docker containers start up the following services:

### Web Interfaces

- **Temporal UI**: [http://localhost:8081](http://localhost:8081) - Temporal UI Dashboard
- **ClickHouse Monitoring 3000**: [http://localhost:3000](http://localhost:3000) - ClickHouse monitoring dashboard
- **CH-UI (ClickHouse UI) 5521**: [http://localhost:5521](http://localhost:5521) - ClickHouse web interface
- **Apache Tika**: [http://localhost:9998](http://localhost:9998) - Document parsing service
- **Minio**: [http://localhost:8084](http://localhost:8084) - Minio S3 Dashboard
  - `hoover4` / `hoover4-secret`

### Search Engines

- **Manticore Search**: [http://localhost:9306](http://localhost:9306) - Primary Manticore instance (SQL port)
- **Manticore Search HTTP**: [http://localhost:9308](http://localhost:9308) - Primary Manticore HTTP API
- **Manticore Search 2**: [http://localhost:19306](http://localhost:19306) - Secondary Manticore instance (SQL port)
- **Manticore Search 2 HTTP**: [http://localhost:19308](http://localhost:19308) - Secondary Manticore HTTP API
- **DejaVu (Elasticsearch UI)**: [http://localhost:1358](http://localhost:1358) - Elasticsearch data browser

### Database Connections

- **Redis**: [http://localhost:6379](http://localhost:6379) - Redis database (TCP, not HTTP)
- **ClickHouse Native**: [http://localhost:9000](http://localhost:9000) - ClickHouse native protocol
- **ClickHouse HTTP Interface**: [http://localhost:8123](http://localhost:8123) - ClickHouse database HTTP API
- **Temporal**: [http://localhost:7233](http://localhost:7233) - Temporal workflow engine
- **Temporal Cassandra**: [http://localhost:9042](http://localhost:9042) - Temporal's Cassandra database
- **Temporal Elasticsearch**: [http://localhost:9200](http://localhost:9200) - Elasticsearch REST API

