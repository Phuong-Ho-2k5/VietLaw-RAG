CREATE TABLE conversations (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	next_sequence INTEGER DEFAULT '1' NOT NULL, 
	in_flight_message_id UUID, 
	fence UUID, 
	lease_until TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
);

CREATE TABLE messages (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	turn_id UUID NOT NULL, 
	sequence INTEGER NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	text TEXT DEFAULT '' NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	result JSONB, 
	request_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(128), 
	request_hash VARCHAR(64), 
	error_code VARCHAR(120), 
	error_status INTEGER, 
	corpus_snapshot_id VARCHAR(64), 
	serving_snapshot_id VARCHAR(64), 
	embedding_profile_id VARCHAR(64), 
	as_of_date VARCHAR(10), 
	PRIMARY KEY (id), 
	UNIQUE (conversation_id, sequence), 
	UNIQUE (conversation_id, idempotency_key), 
	CHECK (role in ('user','assistant')), 
	CHECK (state in ('processing','completed','failed')), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id), 
	FOREIGN KEY(corpus_snapshot_id) REFERENCES corpus_snapshots (id), 
	FOREIGN KEY(serving_snapshot_id) REFERENCES serving_snapshots (id), 
	FOREIGN KEY(embedding_profile_id) REFERENCES embedding_profiles (id)
);

CREATE TABLE retrieval_traces (
	message_id UUID NOT NULL, 
	payload JSONB NOT NULL, 
	PRIMARY KEY (message_id), 
	FOREIGN KEY(message_id) REFERENCES messages (id)
);

CREATE TABLE citations (
	id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	chunk_id VARCHAR(64) NOT NULL, 
	version_id VARCHAR(64) NOT NULL, 
	serving_id VARCHAR(64) NOT NULL, 
	start INTEGER NOT NULL, 
	"end" INTEGER NOT NULL, 
	quote TEXT NOT NULL, 
	metadata JSONB NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(serving_id, chunk_id) REFERENCES serving_snapshot_chunks (serving_id, chunk_id), 
	CHECK ("start" >= 0 AND "end" > "start"), 
	FOREIGN KEY(message_id) REFERENCES messages (id), 
	FOREIGN KEY(chunk_id) REFERENCES retrieval_chunks (id), 
	FOREIGN KEY(version_id) REFERENCES document_versions (id)
);
CREATE INDEX conversations_owner ON conversations(owner_id, created_at DESC, id DESC);
CREATE INDEX messages_turn ON messages(turn_id);
