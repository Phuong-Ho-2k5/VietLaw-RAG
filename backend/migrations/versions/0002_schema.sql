CREATE TABLE corpus_snapshots (
	id VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	complete BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id)
)

;


CREATE TABLE embedding_profiles (
	id VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	PRIMARY KEY (id)
)

;


CREATE TABLE legal_documents (
	id VARCHAR(64) NOT NULL,
	document_number TEXT NOT NULL,
	payload JSONB NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (document_number)
)

;


CREATE TABLE raw_records (
	id VARCHAR(64) NOT NULL,
	zip_hash VARCHAR(64) NOT NULL,
	path TEXT NOT NULL,
	payload JSONB NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (zip_hash, path)
)

;


CREATE TABLE users (
	id UUID NOT NULL,
	username VARCHAR(120) NOT NULL,
	password_hash TEXT NOT NULL,
	role VARCHAR(16) NOT NULL,
	disabled BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CHECK (role in ('admin','user')),
	UNIQUE (username)
)

;


CREATE TABLE document_versions (
	id VARCHAR(64) NOT NULL,
	document_id VARCHAR(64) NOT NULL,
	canonical_text TEXT NOT NULL,
	payload JSONB NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES legal_documents (id)
)

;


CREATE TABLE ingestion_jobs (
	id UUID NOT NULL,
	identity VARCHAR(200) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	payload JSONB NOT NULL,
	actor_id UUID NOT NULL,
	state VARCHAR(16) DEFAULT 'queued' NOT NULL,
	attempt INTEGER DEFAULT '0' NOT NULL,
	fence UUID,
	worker_id TEXT,
	lease_until TIMESTAMP WITH TIME ZONE,
	error VARCHAR(120),
	errors JSONB DEFAULT '[]' NOT NULL,
	PRIMARY KEY (id),
	CHECK (kind in ('import','embedding')),
	CHECK (state in ('queued','running','succeeded','failed')),
	UNIQUE (identity),
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;


CREATE TABLE review_events (
	id UUID NOT NULL,
	actor_id UUID NOT NULL,
	object_id TEXT NOT NULL,
	decision TEXT NOT NULL,
	note TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;


CREATE TABLE serving_snapshots (
	id VARCHAR(64) NOT NULL,
	corpus_id VARCHAR(64) NOT NULL,
	profile_id VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	state VARCHAR(16) DEFAULT 'draft' NOT NULL,
	PRIMARY KEY (id),
	CHECK (state in ('draft','ready','approved','rejected','sealed')),
	FOREIGN KEY(corpus_id) REFERENCES corpus_snapshots (id),
	FOREIGN KEY(profile_id) REFERENCES embedding_profiles (id)
)

;


CREATE TABLE active_corpus (
	singleton BOOLEAN NOT NULL,
	serving_id VARCHAR(64),
	PRIMARY KEY (singleton),
	CHECK (singleton = true),
	FOREIGN KEY(serving_id) REFERENCES serving_snapshots (id)
)

;


CREATE TABLE ingestion_job_items (
	job_id UUID NOT NULL,
	item_id VARCHAR(64) NOT NULL,
	state VARCHAR(16) NOT NULL,
	error VARCHAR(120),
	attempt INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (job_id, item_id),
	CHECK (state in ('pending','running','succeeded','failed','quarantined')),
	FOREIGN KEY(job_id) REFERENCES ingestion_jobs (id)
)

;


CREATE TABLE legal_units (
	id VARCHAR(64) NOT NULL,
	version_id VARCHAR(64) NOT NULL,
	parent_id VARCHAR(64),
	payload JSONB NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(version_id) REFERENCES document_versions (id),
	FOREIGN KEY(parent_id) REFERENCES legal_units (id) DEFERRABLE INITIALLY DEFERRED
)

;


CREATE TABLE retrieval_chunks (
	id VARCHAR(64) NOT NULL,
	version_id VARCHAR(64) NOT NULL,
	text TEXT NOT NULL,
	context_header TEXT NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(version_id) REFERENCES document_versions (id)
)

;


CREATE TABLE version_raw_records (
	version_id VARCHAR(64) NOT NULL,
	raw_id VARCHAR(64) NOT NULL,
	PRIMARY KEY (version_id, raw_id),
	FOREIGN KEY(version_id) REFERENCES document_versions (id),
	FOREIGN KEY(raw_id) REFERENCES raw_records (id)
)

;


CREATE TABLE chunk_embeddings (
	id VARCHAR(64) NOT NULL,
	chunk_id VARCHAR(64) NOT NULL,
	profile_id VARCHAR(64) NOT NULL,
	input_hash VARCHAR(64) NOT NULL,
	vector_hash VARCHAR(64) NOT NULL,
	vector VECTOR(384) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (chunk_id, profile_id, input_hash),
	FOREIGN KEY(chunk_id) REFERENCES retrieval_chunks (id),
	FOREIGN KEY(profile_id) REFERENCES embedding_profiles (id)
)

;


CREATE TABLE chunk_units (
	chunk_id VARCHAR(64) NOT NULL,
	unit_id VARCHAR(64) NOT NULL,
	PRIMARY KEY (chunk_id, unit_id),
	FOREIGN KEY(chunk_id) REFERENCES retrieval_chunks (id),
	FOREIGN KEY(unit_id) REFERENCES legal_units (id)
)

;


CREATE TABLE snapshot_chunks (
	corpus_id VARCHAR(64) NOT NULL,
	chunk_id VARCHAR(64) NOT NULL,
	PRIMARY KEY (corpus_id, chunk_id),
	FOREIGN KEY(corpus_id) REFERENCES corpus_snapshots (id),
	FOREIGN KEY(chunk_id) REFERENCES retrieval_chunks (id)
)

;


CREATE TABLE serving_snapshot_chunks (
	serving_id VARCHAR(64) NOT NULL,
	chunk_id VARCHAR(64) NOT NULL,
	embedding_id VARCHAR(64) NOT NULL,
	PRIMARY KEY (serving_id, chunk_id),
	FOREIGN KEY(serving_id) REFERENCES serving_snapshots (id),
	FOREIGN KEY(chunk_id) REFERENCES retrieval_chunks (id),
	FOREIGN KEY(embedding_id) REFERENCES chunk_embeddings (id)
)

;
