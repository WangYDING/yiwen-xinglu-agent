"""SQLite authority for M4-P1 memory records and lifecycle audit."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.memory.canonical import (
    canonical_json,
    normalize_utc,
    sha256_hex,
    stable_correction_source_id,
    stable_memory_id,
    utc_text,
)
from xuanyi_npc.memory.contracts import (
    AuthoritativeMemoryRecord,
    CorrectionPublicPayload,
    LifecycleAction,
    LifecycleDisposition,
    MemoryCorrectionOperation,
    MemoryHardDeleteOperation,
    MemoryInvalidationOperation,
    MemoryLifecycleOperation,
    MemoryLifecycleResult,
    MemorySourceEventType,
    MemoryStatus,
    MemoryWriteReason,
    ProjectionWriteDisposition,
    ProjectionWriteResult,
    PublicMemoryPayload,
    VerifiedMemorySource,
    authoritative_content_payload,
)
from xuanyi_npc.memory.errors import (
    EmbeddingVectorError,
    InvalidMemoryLifecycleError,
    MemoryEmbeddingConflictError,
    MemoryLifecycleConflictError,
    MemoryNotFoundError,
    MemoryPlayerIsolationError,
    MemorySchemaVersionError,
    MemoryStorageError,
    MemoryStoreCorruptionError,
    MemoryStoreNotInitializedError,
    MemoryTombstonedError,
    ProjectionConflictError,
)
from xuanyi_npc.memory.embeddings import (
    DerivedEmbeddingRecord,
    EmbeddingWriteDisposition,
    EmbeddingWriteResult,
    decode_float32_le,
    encode_float32_le,
    vector_l2_norm,
)
from xuanyi_npc.memory.projection import DeterministicMemoryProjector


LEGACY_MEMORY_SCHEMA_VERSION = 1
MEMORY_SCHEMA_VERSION = 2
CORRECTION_PROJECTION_VERSION = "memory_correction_v1"

_payload_adapter = TypeAdapter(PublicMemoryPayload)


class SQLiteMemoryRepository:
    """Explicitly initialized, single-process SQLite memory authority."""

    CORE_TABLES = frozenset(
        {
            "memory_schema",
            "memory_source_receipts",
            "memory_events",
            "memory_lifecycle_events",
            "memory_tombstones",
        }
    )
    REQUIRED_TABLES = CORE_TABLES | {"memory_embeddings"}

    def __init__(
        self,
        database_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        """Create schema only when explicitly invoked."""

        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._raw_connect()
        except sqlite3.DatabaseError as exc:
            raise MemoryStoreCorruptionError("memory database is invalid") from exc
        except OSError as exc:
            raise MemoryStorageError("failed to open memory database") from exc
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                existing_tables = self._table_names(connection)
                if existing_tables:
                    raise MemorySchemaVersionError(
                        "unversioned memory database is not empty"
                    )
                self._create_schema(connection)
                connection.execute(f"PRAGMA user_version = {MEMORY_SCHEMA_VERSION}")
            elif version == LEGACY_MEMORY_SCHEMA_VERSION:
                self._verify_schema_version(
                    connection,
                    expected_version=LEGACY_MEMORY_SCHEMA_VERSION,
                    required_tables=self.CORE_TABLES,
                )
                self._migrate_v1_to_v2(connection)
            elif version != MEMORY_SCHEMA_VERSION:
                raise MemorySchemaVersionError("memory schema version is incompatible")
            self._verify_schema(connection)
            connection.commit()
        except (MemoryStorageError, MemorySchemaVersionError):
            connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise MemoryStoreCorruptionError("memory database is invalid") from exc
        except Exception as exc:
            connection.rollback()
            raise MemoryStorageError("memory schema initialization failed") from exc
        finally:
            connection.close()

    def schema_version(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()

    def write_projection(
        self,
        source: VerifiedMemorySource,
        memory: AuthoritativeMemoryRecord,
    ) -> ProjectionWriteResult:
        self._validate_projection_pair(source, memory)
        if source.source_event_type is MemorySourceEventType.MEMORY_CORRECTION:
            raise InvalidMemoryLifecycleError(
                "correction memory must use the trusted lifecycle boundary"
            )
        expected = DeterministicMemoryProjector().memory_from_verified_source(source)
        if expected.immutable_projection_json() != memory.immutable_projection_json():
            raise ProjectionConflictError(
                "memory is not the deterministic projection of its public source"
            )

        def operation(connection: sqlite3.Connection) -> ProjectionWriteResult:
            return self._write_projection_in_transaction(connection, source, memory)

        return self._write_transaction(operation)

    def get_memory(
        self,
        *,
        player_id: str,
        memory_id: str,
    ) -> AuthoritativeMemoryRecord:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM memory_events WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            return self._memory_for_player(row, player_id)
        finally:
            connection.close()

    def list_memories(
        self,
        *,
        player_id: str,
        include_inactive: bool = True,
    ) -> tuple[AuthoritativeMemoryRecord, ...]:
        sql = "SELECT * FROM memory_events WHERE player_id = ?"
        parameters: tuple[Any, ...] = (player_id,)
        if not include_inactive:
            sql += " AND status = ?"
            parameters = (player_id, MemoryStatus.ACTIVE.value)
        sql += " ORDER BY memory_id ASC"
        connection = self._connect()
        try:
            rows = connection.execute(sql, parameters).fetchall()
            return tuple(self._memory_from_row(row) for row in rows)
        finally:
            connection.close()

    def write_embeddings(
        self,
        *,
        player_id: str,
        records: tuple[DerivedEmbeddingRecord, ...],
    ) -> tuple[EmbeddingWriteResult, ...]:
        """Write one player's derived vectors atomically."""

        if any(record.player_id != player_id for record in records):
            raise MemoryPlayerIsolationError(
                "embedding batch contains another player's memory"
            )

        def transaction(
            connection: sqlite3.Connection,
        ) -> tuple[EmbeddingWriteResult, ...]:
            return tuple(
                self._upsert_embedding_in_transaction(connection, record)
                for record in records
            )

        return self._write_transaction(transaction)

    def replace_embeddings_for_space(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
        records: tuple[DerivedEmbeddingRecord, ...],
    ) -> tuple[EmbeddingWriteResult, ...]:
        """Atomically rebuild one player's complete derived index for a space."""

        if any(
            record.player_id != player_id
            or record.embedding_space_id != embedding_space_id
            for record in records
        ):
            raise MemoryPlayerIsolationError(
                "embedding rebuild is outside the requested player or space"
            )

        def transaction(
            connection: sqlite3.Connection,
        ) -> tuple[EmbeddingWriteResult, ...]:
            connection.execute(
                """
                DELETE FROM memory_embeddings
                WHERE player_id = ? AND embedding_space_id = ?
                """,
                (player_id, embedding_space_id),
            )
            self._fault_point("embedding_rebuild_after_delete")
            return tuple(
                self._upsert_embedding_in_transaction(connection, record)
                for record in records
            )

        return self._write_transaction(transaction)

    def list_embeddings(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
    ) -> tuple[DerivedEmbeddingRecord, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT derived.* FROM memory_embeddings AS derived
                JOIN memory_events AS authority
                  ON authority.player_id = derived.player_id
                 AND authority.memory_id = derived.memory_id
                WHERE derived.player_id = ?
                  AND derived.embedding_space_id = ?
                  AND authority.status = ?
                ORDER BY derived.memory_id ASC
                """,
                (player_id, embedding_space_id, MemoryStatus.ACTIVE.value),
            ).fetchall()
            return tuple(self._embedding_from_row(row) for row in rows)
        finally:
            connection.close()

    def get_embedding(
        self,
        *,
        player_id: str,
        memory_id: str,
        embedding_space_id: str,
    ) -> DerivedEmbeddingRecord:
        connection = self._connect()
        try:
            authority = connection.execute(
                "SELECT player_id, status FROM memory_events WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            if authority is None:
                raise MemoryNotFoundError("authoritative memory does not exist")
            if authority["player_id"] != player_id:
                raise MemoryPlayerIsolationError("memory belongs to another player")
            if authority["status"] != MemoryStatus.ACTIVE.value:
                raise MemoryNotFoundError("inactive memory has no available embedding")
            row = connection.execute(
                """
                SELECT * FROM memory_embeddings
                WHERE player_id = ? AND memory_id = ? AND embedding_space_id = ?
                """,
                (player_id, memory_id, embedding_space_id),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("derived embedding does not exist")
            return self._embedding_from_row(row)
        finally:
            connection.close()

    def delete_embeddings(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
    ) -> int:
        """Delete only derived vectors for one exact player and space."""

        def transaction(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                DELETE FROM memory_embeddings
                WHERE player_id = ? AND embedding_space_id = ?
                """,
                (player_id, embedding_space_id),
            )
            return int(cursor.rowcount)

        return self._write_transaction(transaction)

    def get_source_receipt(
        self,
        *,
        player_id: str,
        source_event_id: str,
        projection_version: str,
        projection_ordinal: int,
    ) -> VerifiedMemorySource:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM memory_source_receipts
                WHERE player_id = ? AND source_event_id = ? AND projection_version = ?
                  AND projection_ordinal = ?
                """,
                (player_id, source_event_id, projection_version, projection_ordinal),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory source receipt does not exist")
            return self._source_from_row(row)
        finally:
            connection.close()

    def correct_memory(
        self,
        operation: MemoryCorrectionOperation,
    ) -> MemoryLifecycleResult:
        def transaction(connection: sqlite3.Connection) -> MemoryLifecycleResult:
            existing = self._existing_lifecycle(connection, operation)
            if existing is not None:
                return existing
            original = self._memory_for_player(
                connection.execute(
                    "SELECT * FROM memory_events WHERE memory_id = ?",
                    (operation.target_memory_id,),
                ).fetchone(),
                operation.player_id,
            )
            if original.status is not MemoryStatus.ACTIVE:
                raise InvalidMemoryLifecycleError(
                    "only an active memory can be corrected"
                )
            source, replacement = self._correction_projection(original, operation)
            self._write_projection_in_transaction(connection, source, replacement)
            connection.execute(
                "UPDATE memory_events SET status = ? WHERE memory_id = ?",
                (MemoryStatus.SUPERSEDED.value, original.memory_id),
            )
            connection.execute(
                "DELETE FROM memory_embeddings WHERE memory_id = ?",
                (original.memory_id,),
            )
            self._insert_lifecycle(
                connection,
                operation,
                replacement_memory_id=replacement.memory_id,
            )
            self._fault_point("lifecycle_before_commit")
            return MemoryLifecycleResult(
                disposition=LifecycleDisposition.APPLIED,
                operation_id=operation.operation_id,
                target_memory_id=original.memory_id,
                target_status=MemoryStatus.SUPERSEDED,
                replacement_memory_id=replacement.memory_id,
            )

        return self._write_transaction(transaction)

    def invalidate_memory(
        self,
        operation: MemoryInvalidationOperation,
    ) -> MemoryLifecycleResult:
        def transaction(connection: sqlite3.Connection) -> MemoryLifecycleResult:
            existing = self._existing_lifecycle(connection, operation)
            if existing is not None:
                return existing
            target = self._memory_for_player(
                connection.execute(
                    "SELECT * FROM memory_events WHERE memory_id = ?",
                    (operation.target_memory_id,),
                ).fetchone(),
                operation.player_id,
            )
            if target.status is not MemoryStatus.ACTIVE:
                raise InvalidMemoryLifecycleError(
                    "only an active memory can be invalidated"
                )
            connection.execute(
                "UPDATE memory_events SET status = ? WHERE memory_id = ?",
                (MemoryStatus.INVALIDATED.value, target.memory_id),
            )
            connection.execute(
                "DELETE FROM memory_embeddings WHERE memory_id = ?",
                (target.memory_id,),
            )
            self._insert_lifecycle(connection, operation, replacement_memory_id=None)
            self._fault_point("lifecycle_before_commit")
            return MemoryLifecycleResult(
                disposition=LifecycleDisposition.APPLIED,
                operation_id=operation.operation_id,
                target_memory_id=target.memory_id,
                target_status=MemoryStatus.INVALIDATED,
            )

        return self._write_transaction(transaction)

    def hard_delete_memory(
        self,
        operation: MemoryHardDeleteOperation,
    ) -> MemoryLifecycleResult:
        def transaction(connection: sqlite3.Connection) -> MemoryLifecycleResult:
            existing = self._existing_lifecycle(connection, operation)
            if existing is not None:
                return existing
            target = self._memory_for_player(
                connection.execute(
                    "SELECT * FROM memory_events WHERE memory_id = ?",
                    (operation.target_memory_id,),
                ).fetchone(),
                operation.player_id,
            )
            derived_rows = connection.execute(
                """
                WITH RECURSIVE deletion_set(memory_id) AS (
                    SELECT memory_id FROM memory_events
                    WHERE memory_id = ? AND player_id = ?
                    UNION ALL
                    SELECT child.memory_id
                    FROM memory_events AS child
                    JOIN deletion_set AS parent
                      ON child.supersedes_memory_id = parent.memory_id
                    WHERE child.player_id = ?
                )
                SELECT memory_events.* FROM memory_events
                JOIN deletion_set USING (memory_id)
                ORDER BY memory_events.memory_id
                """,
                (
                    target.memory_id,
                    target.player_id,
                    target.player_id,
                ),
            ).fetchall()
            derived = tuple(self._memory_from_row(row) for row in derived_rows)
            self._insert_lifecycle(connection, operation, replacement_memory_id=None)
            for item in derived:
                receipt = connection.execute(
                    """
                    SELECT 1 FROM memory_source_receipts
                    WHERE player_id = ? AND source_event_id = ?
                      AND projection_version = ?
                      AND projection_ordinal = ?
                    """,
                    (
                        item.player_id,
                        item.source_event_id,
                        item.projection_version,
                        item.projection_ordinal,
                    ),
                ).fetchone()
                if receipt is None:
                    raise MemoryStoreCorruptionError(
                        "memory source receipt is missing"
                    )
                connection.execute(
                    """
                    INSERT INTO memory_tombstones (
                        memory_id, player_id, source_event_id, projection_version,
                        projection_ordinal, content_hash, public_payload_hash,
                        operation_id, reason_code, trusted_boundary, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.memory_id,
                        item.player_id,
                        item.source_event_id,
                        item.projection_version,
                        item.projection_ordinal,
                        item.content_hash,
                        item.public_payload_hash,
                        operation.operation_id,
                        operation.reason.value,
                        operation.trusted_boundary.value,
                        utc_text(operation.occurred_at),
                    ),
                )
            connection.executemany(
                "DELETE FROM memory_events WHERE memory_id = ?",
                ((item.memory_id,) for item in derived),
            )
            connection.executemany(
                """
                DELETE FROM memory_source_receipts
                WHERE player_id = ? AND source_event_id = ?
                  AND projection_version = ?
                  AND projection_ordinal = ?
                """,
                (
                    (
                        item.player_id,
                        item.source_event_id,
                        item.projection_version,
                        item.projection_ordinal,
                    )
                    for item in derived
                ),
            )
            self._fault_point("hard_delete_after_content_delete")
            return MemoryLifecycleResult(
                disposition=LifecycleDisposition.APPLIED,
                operation_id=operation.operation_id,
                target_memory_id=target.memory_id,
                hard_deleted=True,
            )

        return self._write_transaction(transaction)

    def table_counts(self) -> dict[str, int]:
        connection = self._connect()
        try:
            return {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in sorted(self.REQUIRED_TABLES - {"memory_schema"})
            }
        finally:
            connection.close()

    def tombstone_exists(self, memory_id: str) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM memory_tombstones WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def _write_projection_in_transaction(
        self,
        connection: sqlite3.Connection,
        source: VerifiedMemorySource,
        memory: AuthoritativeMemoryRecord,
    ) -> ProjectionWriteResult:
        self._validate_projection_pair(source, memory)
        tombstone = connection.execute(
            """
            SELECT 1 FROM memory_tombstones
            WHERE memory_id = ? OR (
                player_id = ? AND source_event_id = ?
                AND projection_version = ? AND projection_ordinal = ?
            )
            """,
            (
                memory.memory_id,
                memory.player_id,
                memory.source_event_id,
                memory.projection_version,
                memory.projection_ordinal,
            ),
        ).fetchone()
        if tombstone is not None:
            raise MemoryTombstonedError("deleted memory cannot be projected again")

        receipt_row = connection.execute(
            """
            SELECT * FROM memory_source_receipts
            WHERE player_id = ? AND source_event_id = ?
              AND projection_version = ?
              AND projection_ordinal = ?
            """,
            (
                source.player_id,
                source.source_event_id,
                source.projection_version,
                source.projection_ordinal,
            ),
        ).fetchone()
        memory_row = connection.execute(
            """
            SELECT * FROM memory_events
            WHERE player_id = ? AND source_event_id = ?
              AND projection_version = ? AND projection_ordinal = ?
            """,
            (
                memory.player_id,
                memory.source_event_id,
                memory.projection_version,
                memory.projection_ordinal,
            ),
        ).fetchone()

        if receipt_row is not None or memory_row is not None:
            if receipt_row is None or memory_row is None:
                raise MemoryStoreCorruptionError(
                    "memory projection is only partially stored"
                )
            existing_source = self._source_from_row(receipt_row)
            existing_memory = self._memory_from_row(memory_row)
            if existing_source != source:
                if existing_source.player_id != source.player_id:
                    raise MemoryPlayerIsolationError(
                        "source identity is already owned by another player"
                    )
                raise ProjectionConflictError("public source payload conflicts")
            if (
                existing_memory.immutable_projection_json()
                != memory.immutable_projection_json()
            ):
                raise ProjectionConflictError("projected memory content conflicts")
            return ProjectionWriteResult(
                disposition=ProjectionWriteDisposition.IDEMPOTENT,
                memory_id=existing_memory.memory_id,
                source_event_id=existing_memory.source_event_id,
                memory_status=existing_memory.status,
            )

        collision = connection.execute(
            "SELECT player_id FROM memory_events WHERE memory_id = ?",
            (memory.memory_id,),
        ).fetchone()
        if collision is not None:
            if collision["player_id"] != memory.player_id:
                raise MemoryPlayerIsolationError(
                    "memory identity is already owned by another player"
                )
            raise ProjectionConflictError("memory identity collision")

        connection.execute(
            """
            INSERT INTO memory_source_receipts (
                source_event_id, projection_version, projection_ordinal,
                player_id, source_session_id, source_event_type,
                source_sequence, source_revision, occurred_at,
                public_payload_json, public_payload_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_event_id,
                source.projection_version,
                source.projection_ordinal,
                source.player_id,
                source.source_session_id,
                source.source_event_type.value,
                source.source_sequence,
                source.source_revision,
                utc_text(source.occurred_at),
                canonical_json(source.public_payload),
                source.public_payload_hash,
                utc_text(self._now()),
            ),
        )
        self._fault_point("projection_after_receipt")
        connection.execute(
            """
            INSERT INTO memory_events (
                memory_id, player_id, memory_type, content, importance,
                related_case_id, related_entity_ids_json,
                relationship_impacts_json, occurred_at, source_event_id,
                source_session_id, source_event_type, source_sequence,
                source_revision, projection_version, projection_ordinal,
                write_reason, public_payload_hash, content_hash, status,
                supersedes_memory_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.memory_id,
                memory.player_id,
                memory.memory_type.value,
                memory.content,
                memory.importance,
                memory.related_case_id,
                canonical_json(sorted(memory.related_entity_ids)),
                "[]",
                utc_text(memory.occurred_at),
                memory.source_event_id,
                memory.source_session_id,
                memory.source_event_type.value,
                memory.source_sequence,
                memory.source_revision,
                memory.projection_version,
                memory.projection_ordinal,
                memory.write_reason.value,
                memory.public_payload_hash,
                memory.content_hash,
                memory.status.value,
                memory.supersedes_memory_id,
                utc_text(self._now()),
            ),
        )
        return ProjectionWriteResult(
            disposition=ProjectionWriteDisposition.CREATED,
            memory_id=memory.memory_id,
            source_event_id=memory.source_event_id,
            memory_status=memory.status,
        )

    def _upsert_embedding_in_transaction(
        self,
        connection: sqlite3.Connection,
        record: DerivedEmbeddingRecord,
    ) -> EmbeddingWriteResult:
        memory = self._memory_for_player(
            connection.execute(
                "SELECT * FROM memory_events WHERE memory_id = ?",
                (record.memory_id,),
            ).fetchone(),
            record.player_id,
        )
        if memory.status is not MemoryStatus.ACTIVE:
            raise MemoryEmbeddingConflictError(
                "only active authoritative memory can be indexed"
            )
        if memory.content_hash != record.content_hash:
            raise MemoryEmbeddingConflictError(
                "embedding content hash does not match authoritative memory"
            )
        declared_dimension = connection.execute(
            """
            SELECT dimension FROM memory_embeddings
            WHERE embedding_space_id = ?
            LIMIT 1
            """,
            (record.embedding_space_id,),
        ).fetchone()
        if (
            declared_dimension is not None
            and int(declared_dimension["dimension"]) != record.dimension
        ):
            raise MemoryEmbeddingConflictError(
                "embedding space already uses a different fixed dimension"
            )

        vector_blob = encode_float32_le(record.vector)
        stored_vector = decode_float32_le(vector_blob, dimension=record.dimension)
        stored_norm = vector_l2_norm(stored_vector)
        existing_row = connection.execute(
            """
            SELECT * FROM memory_embeddings
            WHERE memory_id = ? AND embedding_space_id = ?
            """,
            (record.memory_id, record.embedding_space_id),
        ).fetchone()
        if existing_row is not None:
            existing = self._embedding_from_row(existing_row)
            if existing.player_id != record.player_id:
                raise MemoryPlayerIsolationError(
                    "embedding identity belongs to another player"
                )
            if (
                existing.content_hash == record.content_hash
                and existing.dimension == record.dimension
                and bytes(existing_row["vector_blob"]) == vector_blob
            ):
                return EmbeddingWriteResult(
                    memory_id=record.memory_id,
                    embedding_space_id=record.embedding_space_id,
                    disposition=EmbeddingWriteDisposition.IDEMPOTENT,
                )
            if existing.content_hash == record.content_hash:
                raise MemoryEmbeddingConflictError(
                    "embedding vector conflicts for unchanged authoritative content"
                )
            disposition = EmbeddingWriteDisposition.REBUILT
            connection.execute(
                """
                UPDATE memory_embeddings
                SET player_id = ?, content_hash = ?, dimension = ?,
                    vector_blob = ?, l2_norm = ?, generated_at = ?
                WHERE memory_id = ? AND embedding_space_id = ?
                """,
                (
                    record.player_id,
                    record.content_hash,
                    record.dimension,
                    vector_blob,
                    stored_norm,
                    utc_text(record.generated_at),
                    record.memory_id,
                    record.embedding_space_id,
                ),
            )
        else:
            disposition = EmbeddingWriteDisposition.CREATED
            connection.execute(
                """
                INSERT INTO memory_embeddings (
                    memory_id, player_id, embedding_space_id, content_hash,
                    dimension, vector_blob, l2_norm, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.player_id,
                    record.embedding_space_id,
                    record.content_hash,
                    record.dimension,
                    vector_blob,
                    stored_norm,
                    utc_text(record.generated_at),
                ),
            )
        return EmbeddingWriteResult(
            memory_id=record.memory_id,
            embedding_space_id=record.embedding_space_id,
            disposition=disposition,
        )

    def _correction_projection(
        self,
        original: AuthoritativeMemoryRecord,
        operation: MemoryCorrectionOperation,
    ) -> tuple[VerifiedMemorySource, AuthoritativeMemoryRecord]:
        source_event_id = stable_correction_source_id(operation.operation_id)
        payload = CorrectionPublicPayload(
            operation_id=operation.operation_id,
            related_case_id=original.related_case_id,
            target_memory_id=original.memory_id,
            replacement_public_content=operation.replacement_public_content,
            reason=operation.reason.value,
        )
        payload_hash = sha256_hex(payload)
        source = VerifiedMemorySource(
            source_event_id=source_event_id,
            player_id=original.player_id,
            source_session_id=original.source_session_id,
            source_event_type=MemorySourceEventType.MEMORY_CORRECTION,
            source_sequence=original.source_sequence,
            source_revision=original.source_revision,
            projection_version=CORRECTION_PROJECTION_VERSION,
            projection_ordinal=0,
            occurred_at=operation.occurred_at,
            public_payload=payload,
            public_payload_hash=payload_hash,
        )
        content_hash = sha256_hex(
            authoritative_content_payload(
                memory_type=original.memory_type,
                content=operation.replacement_public_content,
                importance=original.importance,
                related_case_id=original.related_case_id,
                related_entity_ids=original.related_entity_ids,
            )
        )
        replacement = AuthoritativeMemoryRecord(
            memory_id=stable_memory_id(
                original.player_id,
                source_event_id,
                CORRECTION_PROJECTION_VERSION,
                0,
            ),
            player_id=original.player_id,
            memory_type=original.memory_type,
            content=operation.replacement_public_content,
            importance=original.importance,
            related_case_id=original.related_case_id,
            related_entity_ids=original.related_entity_ids,
            relationship_impacts=(),
            occurred_at=operation.occurred_at,
            source_event_id=source_event_id,
            source_session_id=original.source_session_id,
            source_event_type=MemorySourceEventType.MEMORY_CORRECTION,
            source_sequence=original.source_sequence,
            source_revision=original.source_revision,
            projection_version=CORRECTION_PROJECTION_VERSION,
            projection_ordinal=0,
            write_reason=MemoryWriteReason.VERIFIED_MEMORY_CORRECTION,
            public_payload_hash=payload_hash,
            content_hash=content_hash,
            supersedes_memory_id=original.memory_id,
        )
        return source, replacement

    def _existing_lifecycle(
        self,
        connection: sqlite3.Connection,
        operation: MemoryLifecycleOperation,
    ) -> MemoryLifecycleResult | None:
        row = connection.execute(
            "SELECT * FROM memory_lifecycle_events WHERE operation_id = ?",
            (operation.operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["operation_fingerprint"] != sha256_hex(operation):
            raise MemoryLifecycleConflictError("lifecycle operation id conflicts")
        target_status: MemoryStatus | None = None
        target = connection.execute(
            "SELECT status, player_id FROM memory_events WHERE memory_id = ?",
            (operation.target_memory_id,),
        ).fetchone()
        if target is not None:
            if target["player_id"] != operation.player_id:
                raise MemoryPlayerIsolationError(
                    "lifecycle target belongs to another player"
                )
            target_status = MemoryStatus(target["status"])
        return MemoryLifecycleResult(
            disposition=LifecycleDisposition.IDEMPOTENT,
            operation_id=operation.operation_id,
            target_memory_id=operation.target_memory_id,
            target_status=target_status,
            replacement_memory_id=row["replacement_memory_id"],
            hard_deleted=row["action"] == LifecycleAction.HARD_DELETE.value,
        )

    def _insert_lifecycle(
        self,
        connection: sqlite3.Connection,
        operation: MemoryLifecycleOperation,
        *,
        replacement_memory_id: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memory_lifecycle_events (
                operation_id, request_id, action, player_id, target_memory_id,
                replacement_memory_id, reason_code, trusted_boundary,
                occurred_at, operation_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation.operation_id,
                operation.request_id,
                operation.action.value,
                operation.player_id,
                operation.target_memory_id,
                replacement_memory_id,
                operation.reason.value,
                operation.trusted_boundary.value,
                utc_text(operation.occurred_at),
                sha256_hex(operation),
                utc_text(self._now()),
            ),
        )

    @staticmethod
    def _validate_projection_pair(
        source: VerifiedMemorySource,
        memory: AuthoritativeMemoryRecord,
    ) -> None:
        fields = (
            "player_id",
            "source_event_id",
            "source_session_id",
            "source_event_type",
            "source_sequence",
            "source_revision",
            "projection_version",
            "projection_ordinal",
            "occurred_at",
            "public_payload_hash",
        )
        if any(getattr(source, field) != getattr(memory, field) for field in fields):
            if source.player_id != memory.player_id:
                raise MemoryPlayerIsolationError(
                    "source and memory players do not match"
                )
            raise ProjectionConflictError("source chain does not match memory record")

    def _write_transaction(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = operation(connection)
            connection.commit()
            return result
        except MemoryStorageError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ProjectionConflictError("memory uniqueness constraint failed") from exc
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise MemoryStoreCorruptionError("memory database write failed") from exc
        except Exception as exc:
            connection.rollback()
            raise MemoryStorageError("memory transaction failed") from exc
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise MemoryStoreNotInitializedError("memory database is not initialized")
        try:
            connection = self._raw_connect()
            self._verify_schema(connection)
            return connection
        except MemoryStorageError:
            if "connection" in locals():
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if "connection" in locals():
                connection.close()
            raise MemoryStoreCorruptionError("memory database is invalid") from exc

    def _raw_connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        self._verify_schema_version(
            connection,
            expected_version=MEMORY_SCHEMA_VERSION,
            required_tables=self.REQUIRED_TABLES,
        )

    def _verify_schema_version(
        self,
        connection: sqlite3.Connection,
        *,
        expected_version: int,
        required_tables: frozenset[str] | set[str],
    ) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:
            raise MemoryStoreNotInitializedError("memory database is not initialized")
        if version != expected_version:
            raise MemorySchemaVersionError("memory schema version is incompatible")
        tables = self._table_names(connection)
        if not set(required_tables).issubset(tables):
            raise MemoryStoreCorruptionError("memory schema is incomplete")
        row = connection.execute(
            "SELECT version FROM memory_schema WHERE singleton = 1"
        ).fetchone()
        if row is None or int(row["version"]) != expected_version:
            raise MemorySchemaVersionError("memory schema metadata is incompatible")

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        self._create_embedding_schema(connection)
        self._fault_point("migration_after_embedding_table")
        connection.execute(
            "UPDATE memory_schema SET version = ? WHERE singleton = 1",
            (MEMORY_SCHEMA_VERSION,),
        )
        connection.execute(f"PRAGMA user_version = {MEMORY_SCHEMA_VERSION}")

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE memory_schema (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                version INTEGER NOT NULL CHECK (version >= 1)
            )
            """,
            """
            CREATE TABLE memory_source_receipts (
                source_event_id TEXT NOT NULL,
                projection_version TEXT NOT NULL,
                projection_ordinal INTEGER NOT NULL CHECK (projection_ordinal >= 0),
                player_id TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                source_event_type TEXT NOT NULL,
                source_sequence INTEGER NOT NULL CHECK (source_sequence >= 1),
                source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
                occurred_at TEXT NOT NULL,
                public_payload_json TEXT NOT NULL,
                public_payload_hash TEXT NOT NULL CHECK (length(public_payload_hash) = 64),
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    player_id, source_event_id,
                    projection_version, projection_ordinal
                )
            )
            """,
            """
            CREATE TABLE memory_events (
                memory_id TEXT PRIMARY KEY,
                player_id TEXT NOT NULL,
                memory_type TEXT NOT NULL CHECK (memory_type IN ('episodic', 'learning')),
                content TEXT NOT NULL,
                importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
                related_case_id TEXT,
                related_entity_ids_json TEXT NOT NULL,
                relationship_impacts_json TEXT NOT NULL CHECK (relationship_impacts_json = '[]'),
                occurred_at TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                source_event_type TEXT NOT NULL,
                source_sequence INTEGER NOT NULL CHECK (source_sequence >= 1),
                source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
                projection_version TEXT NOT NULL,
                projection_ordinal INTEGER NOT NULL CHECK (projection_ordinal >= 0),
                write_reason TEXT NOT NULL,
                public_payload_hash TEXT NOT NULL CHECK (length(public_payload_hash) = 64),
                content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
                status TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'invalidated')),
                supersedes_memory_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (player_id, source_event_id, projection_version, projection_ordinal),
                FOREIGN KEY (
                    player_id, source_event_id,
                    projection_version, projection_ordinal
                )
                    REFERENCES memory_source_receipts (
                        player_id, source_event_id,
                        projection_version, projection_ordinal
                    )
            )
            """,
            """
            CREATE TABLE memory_lifecycle_events (
                operation_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('correct', 'invalidate', 'hard_delete')),
                player_id TEXT NOT NULL,
                target_memory_id TEXT NOT NULL,
                replacement_memory_id TEXT,
                reason_code TEXT NOT NULL,
                trusted_boundary TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                operation_fingerprint TEXT NOT NULL CHECK (length(operation_fingerprint) = 64),
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE memory_tombstones (
                memory_id TEXT PRIMARY KEY,
                player_id TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                projection_version TEXT NOT NULL,
                projection_ordinal INTEGER NOT NULL CHECK (projection_ordinal >= 0),
                content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
                public_payload_hash TEXT NOT NULL CHECK (length(public_payload_hash) = 64),
                operation_id TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                trusted_boundary TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                UNIQUE (player_id, source_event_id, projection_version, projection_ordinal)
            )
            """,
            "CREATE INDEX idx_memory_events_player_status ON memory_events (player_id, status)",
            "CREATE INDEX idx_memory_events_session ON memory_events (source_session_id)",
            "CREATE INDEX idx_memory_lifecycle_player ON memory_lifecycle_events (player_id)",
        )
        for statement in statements:
            connection.execute(statement)
        SQLiteMemoryRepository._create_embedding_schema(connection)
        connection.execute(
            "INSERT INTO memory_schema (singleton, version) VALUES (1, ?)",
            (MEMORY_SCHEMA_VERSION,),
        )

    @staticmethod
    def _create_embedding_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_events_player_memory
            ON memory_events (player_id, memory_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE memory_embeddings (
                memory_id TEXT NOT NULL,
                player_id TEXT NOT NULL,
                embedding_space_id TEXT NOT NULL,
                content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
                dimension INTEGER NOT NULL CHECK (dimension BETWEEN 1 AND 4096),
                vector_blob BLOB NOT NULL CHECK (
                    typeof(vector_blob) = 'blob'
                    AND length(vector_blob) = dimension * 4
                ),
                l2_norm REAL NOT NULL CHECK (l2_norm > 0),
                generated_at TEXT NOT NULL,
                PRIMARY KEY (memory_id, embedding_space_id),
                FOREIGN KEY (player_id, memory_id)
                    REFERENCES memory_events (player_id, memory_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_memory_embeddings_player_space
            ON memory_embeddings (player_id, embedding_space_id)
            """
        )

    def _source_from_row(self, row: sqlite3.Row) -> VerifiedMemorySource:
        try:
            payload = _payload_adapter.validate_python(
                json.loads(row["public_payload_json"])
            )
            return VerifiedMemorySource(
                source_event_id=row["source_event_id"],
                player_id=row["player_id"],
                source_session_id=row["source_session_id"],
                source_event_type=row["source_event_type"],
                source_sequence=row["source_sequence"],
                source_revision=row["source_revision"],
                projection_version=row["projection_version"],
                projection_ordinal=row["projection_ordinal"],
                occurred_at=self._parse_time(row["occurred_at"]),
                public_payload=payload,
                public_payload_hash=row["public_payload_hash"],
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MemoryStoreCorruptionError(
                "stored memory source receipt is invalid"
            ) from exc

    def _memory_from_row(self, row: sqlite3.Row) -> AuthoritativeMemoryRecord:
        try:
            related_entities = frozenset(json.loads(row["related_entity_ids_json"]))
            relationship_impacts = tuple(
                json.loads(row["relationship_impacts_json"])
            )
            return AuthoritativeMemoryRecord(
                memory_id=row["memory_id"],
                player_id=row["player_id"],
                memory_type=MemoryType(row["memory_type"]),
                content=row["content"],
                importance=row["importance"],
                related_case_id=row["related_case_id"],
                related_entity_ids=related_entities,
                relationship_impacts=relationship_impacts,
                occurred_at=self._parse_time(row["occurred_at"]),
                source_event_id=row["source_event_id"],
                source_session_id=row["source_session_id"],
                source_event_type=row["source_event_type"],
                source_sequence=row["source_sequence"],
                source_revision=row["source_revision"],
                projection_version=row["projection_version"],
                projection_ordinal=row["projection_ordinal"],
                write_reason=row["write_reason"],
                public_payload_hash=row["public_payload_hash"],
                content_hash=row["content_hash"],
                status=row["status"],
                supersedes_memory_id=row["supersedes_memory_id"],
            )
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MemoryStoreCorruptionError(
                "stored authoritative memory is invalid"
            ) from exc

    def _embedding_from_row(self, row: sqlite3.Row) -> DerivedEmbeddingRecord:
        try:
            dimension = int(row["dimension"])
            vector = decode_float32_le(
                bytes(row["vector_blob"]),
                dimension=dimension,
            )
            stored_norm = float(row["l2_norm"])
            if not stored_norm > 0.0:
                raise EmbeddingVectorError("stored embedding norm is invalid")
            return DerivedEmbeddingRecord(
                memory_id=row["memory_id"],
                player_id=row["player_id"],
                embedding_space_id=row["embedding_space_id"],
                content_hash=row["content_hash"],
                dimension=dimension,
                vector=vector,
                l2_norm=stored_norm,
                generated_at=self._parse_time(row["generated_at"]),
            )
        except (ValidationError, ValueError, TypeError, EmbeddingVectorError) as exc:
            raise MemoryStoreCorruptionError(
                "stored derived embedding is invalid"
            ) from exc

    def _memory_for_player(
        self,
        row: sqlite3.Row | None,
        player_id: str,
    ) -> AuthoritativeMemoryRecord:
        if row is None:
            raise MemoryNotFoundError("memory does not exist")
        if row["player_id"] != player_id:
            raise MemoryPlayerIsolationError("memory belongs to another player")
        return self._memory_from_row(row)

    def _now(self) -> datetime:
        return normalize_utc(self._clock())

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return normalize_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))

    def _fault_point(self, name: str) -> None:
        """Test seam for proving transaction rollback; production does nothing."""

        del name
