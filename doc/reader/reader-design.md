# nov_gnsspq Reader Frontend: Design Document

## Purpose and Scope

The reader frontend provides structured, filter-capable access to a nov_gnsspq Parquet database produced by `PqConverter`. Where the writer converts raw NovAtel GPS log files into a directory tree of Parquet files with relational identity columns, the reader reconstructs that tree into a navigable Python object hierarchy and exposes filtering, aggregation, and iteration over its contents.

The reader is intentionally narrow in scope. It does not implement a query engine, expose a SQL interface, or build secondary indices over the Parquet files. It loads all data for each table eagerly at construction time using `pd.read_parquet`, and all subsequent operations work against the in-memory DataFrames. This design trades memory for simplicity and keeps the API surface small. The reader is designed for interactive analysis workflows and test harnesses, not for processing databases too large to fit in RAM.

The frontend is the sole public interface into the reader subsystem. No other module in `nov_gnsspq.reader` needs to be imported by callers.

---

## Class Hierarchy

```
LogFrame
├── PqReader
└── LogTableFrame
    ├── LogTable
    └── LogSubtable
```

`LogFrame` is the base class that handles Parquet loading, subtable discovery, tree rendering, and column enumeration. `PqReader` extends `LogFrame` as the top-level entry point: it wraps schema detection, provides iteration over the full message sequence, and exposes database-wide filter and sort operations. `LogTableFrame` extends `LogFrame` with filtering, aggregation, and dynamic dataclass generation for per-row access. `LogTable` extends `LogTableFrame` with time-aware filtering and sorting for top-level message tables. `LogSubtable` extends `LogTableFrame` without additional behaviour, existing as a distinct type so that `LogTable._child_type` can return `LogSubtable` rather than another `LogTable`, establishing depth-limited recursive construction.

`FieldValue` is composed onto every `LogTableFrame` instance at construction: one attribute is set per column name, giving callers property-style access to per-field aggregates without calling methods directly. `Utils` is a static-only class providing `convert_time_format` and the ASCII tree rendering used by `__repr__`.

---

## Schema Configuration

`SchemaConfig` is a frozen dataclass that encodes the column names used by the database schema into a single object passed through the entire class tree at construction time. The three fields are `week_col` (`"header_week"`), `milliseconds_col` (`"header_milliseconds"`), and `sequence_id_col` (`"sequence_id"`). A single module-level singleton `_SCHEMA` holds the current values; all `LogFrame` subclass constructors accept a `schema` keyword (defaulting to `_SCHEMA`) and store it as `self._schema`, making all column-name decisions data-driven rather than scattered hardcoded strings.

---

## Selective Loading

`PqReader` supports two mechanisms for limiting the data loaded at construction time, both useful for reducing memory consumption when only a subset of the database is needed.

The `logs` parameter accepts a list of log type names, such as `["BESTPOS", "RANGE"]`. When supplied, `PqReader._get_subtables` restricts subdirectory instantiation to only those names, and each call to `pd.read_parquet` receives a filter predicate on the `log` column, pushing the selection down to the Parquet layer. Log types not named in the list are never instantiated and their files are never read into memory.

The `db_path` argument accepts either a path to a database directory or a path to a `.zip` archive produced by `zip_database`. When a zip path is given, the constructor extracts the archive into a `tempfile.TemporaryDirectory`, stores the directory object as `self._tmpdir` to keep it alive for the lifetime of the `PqReader` instance, then derives the effective `db_path` from the archive stem. The extracted directory is cleaned up automatically when the instance is garbage collected. The two mechanisms compose: passing both a zip path and a `logs` list extracts the archive first, then applies the log filter during subtable construction.

---

## LogFrame: Base Class

`LogFrame.__init__` executes a fixed four-step construction sequence. First, `_get_subtables` scans the filesystem by listing the folder path and retaining entries that are directories; each directory is assumed to be a child table and is instantiated recursively using `self._child_type` as the constructor. Second, `pd.read_parquet` loads the Parquet file for this node. Third, `cur_table` is initialised as a reference to the full `table` DataFrame; all filter operations narrow `cur_table` without modifying `table`, which retains the unfiltered data for `reset_filters`. Fourth, `_get_subtable_class` wraps the subtable dict in a dynamically generated dataclass so that attribute access on `self.subtables` provides IDE-friendly navigation (e.g., `db.subtables.RANGE`).

`_get_subtable_class` uses `dataclasses.make_dataclass` to build a throwaway class whose fields correspond to each discovered subtable name and whose `__repr__` renders a bracketed comma-separated list of subtable names. This pattern gives callers discoverable attribute access on `subtables` without requiring any static class definitions per message type.

`get_columns` performs a depth-first traversal of the subtable tree, accumulating column names from each node's `table.columns` and extending the result with child contributions. This provides a flat view of every column reachable from any node in the subtree.

`_check_time_info` validates that the schema-appropriate time columns (`week_col` and `milliseconds_col` from `self._schema`) are present in `cur_table`. Any time-based operation calls this guard first, raising `FieldNotFoundError` if the table lacks the necessary columns. `__repr__` delegates to `Utils.stringify_tree`, which is given the result of `_get_tree`, a recursively assembled dict of display strings, to produce a Unicode box-drawing tree of table names, entry counts, and field counts.

---

## PqReader: Top-Level Entry Point

`PqReader.__init__` resolves the input path before delegating to `LogFrame.__init__`. If `db_path` ends with `.zip`, the archive is extracted to a temporary directory as described in the Selective Loading section; otherwise, `db_path` is used directly. The constructor also passes `_SCHEMA` to the parent constructor and attempts to load `unknown_data.parquet` from the root, silently ignoring `FileNotFoundError` if the writer omitted the file because no unknown messages were encountered. The database name is extracted with `os.path.split` and used as `table_name` for the log table lookup.

`filter_by_log` narrows `cur_table` to rows matching a single log type by name-equality on the `log` column. `sort_by_time` performs a cross-table sort without relying on DataFrame indices, which would overlap between subtables: it collects `(sequence_id, week, ms)` triples from each subtable whose columns include all three fields, concatenates them with `ignore_index=True`, sorts by `(week_col, milliseconds_col)`, then builds a `sequence_id`-to-sort-position mapping and reorders `cur_table` using `iloc[argsort]`. This ensures the sort is driven entirely by `sequence_id` values shared between the root table and its children, not by positional indices that are independently 0-based per subtable. `reset_filters` restores `cur_table` to the full `table` reference at the `PqReader` level and cascades `reset_filters` into each subtable.

`__iter__` walks `cur_table` row by row using `iterrows`, extracting the `sequence_id_col` value and log name from each row, then looking up the corresponding `LogTable` from `self._subtables`. It builds a boolean mask on the `sequence_id` column and slices accordingly. When the mask matches more than one row — an edge case that should not arise in a well-formed database but is not structurally prevented — `iloc[0]` selects the first match, ensuring that `create_log_entry` always receives a `pd.Series` rather than a `DataFrame`.

---

## LogTableFrame: Filtering and Aggregation

`filter_entries` is the primary filtering API. It handles three cases: when a `subtable` argument is supplied, the filter is routed through `_filter_by_subtable` to compute the set of parent IDs that satisfy the predicate, then `cur_table` is narrowed to matching rows and all child subtables are cascaded via `_filter_down`; when the field is found directly in the current table's columns, a pandas `.query()` expression is evaluated and the same cascade is applied; when the field is absent from the current table but found in a child subtable, a `FieldNotFoundError` is raised with a corrective hint suggesting the user supply the subtable argument.

`_filter_by_subtable` implements recursive descent into the subtable tree. When the `subtable` tuple still has elements, it recurses into the named child and collects its allowed parent IDs, then maps those through the current level's `sequence_id` column. At the leaf level, if an `operation` is provided, it is dispatched through the module-level `_SUMMARY_OPS` dict, which maps allowed operation names to callable lambdas; comparators are similarly resolved through `_COMPARATORS`. No `eval` is involved at any stage. Without an `operation`, a simple `.query()` expression is evaluated directly. The returned IDs come from the `parent_id` column.

`_filter_down` propagates a parent ID set downward through the subtable tree. It filters on the `parent_id` column using `.isin`, then recurses into child subtables passing the current level's `sequence_id` values, ensuring that the entire subtree remains consistent with the parent's active filter.

Aggregation is unified through `_get_summary_stats`, which dispatches to `_apply_summary_op`. If `group=True`, it groups by the `parent_id` column before applying the operation. `_apply_summary_op` resolves the operation name through the `_SUMMARY_OPS` dispatch table and raises `ValueError` for any name not present, making the allowed set explicit and closed. The public aggregation methods `get_mean`, `get_median`, `get_min`, `get_max`, `get_sum`, and `get_std` are thin wrappers over `_get_summary_stats`.

`create_log_data_class` builds a per-table dataclass schema using `dataclasses.make_dataclass`. It recurses into subtables, collecting their own dataclass definitions, then combines those with the current table's column names and dtypes as the field list. The resulting class is stored as `self.log_data_class`. `create_log_entry` instantiates that class for a single row, populating subtable fields by looking up child rows via `parent_id` and recursing. Each field on a `LogTableFrame` instance is additionally exposed as a `FieldValue` attribute, set via `setattr` in `__init__` for every column name in `cur_table.columns`.

---

## LogTable: Time-Aware Tables

`LogTable` extends `LogTableFrame` with five methods that treat the table as a time-ordered sequence of NovAtel messages. GPS time is represented as a (week, milliseconds) pair: a GPS week number (integer) and milliseconds elapsed since the start of that week, matching the column scheme established by `SchemaConfig`.

`sort_by_time` calls `_check_time_info`, then sorts `cur_table` in-place by the schema-appropriate time columns. `time_range` returns a `(GPSTime, GPSTime)` tuple representing the earliest and latest timestamps in `cur_table`. `filter_start_time` and `filter_end_time` build compound boolean masks: entries in a later GPS week pass unconditionally; entries in the same week are tested against the millisecond threshold. `filter_time_range` composes those two methods sequentially. All time-filtering methods accept either a `GPSTime` or a `datetime.datetime`, converting the latter via `Utils.convert_time_format`.

`LogTable` overrides `_child_type` to return `LogSubtable`, ensuring that child tables discovered during construction are instantiated as `LogSubtable` rather than as another `LogTable`. `LogSubtable` overrides `_child_type` to return itself, allowing arbitrarily deep nesting while keeping the type distinct from `LogTable`.

---

## Public API Contract

### `PqReader`

| Method | Description |
|---|---|
| `filter_by_log(log_name)` | Narrows `cur_table` to rows whose `log` column matches `log_name`. |
| `sort_by_time()` | Reorders `cur_table` by the chronological order derived from all subtables' time columns. |
| `reset_filters()` | Restores `cur_table` to the full unfiltered table at the database level. |
| `__iter__()` | Yields `(log_name, log_entry)` tuples for each row in `cur_table`, respecting active filters. |
| `get_columns()` | Returns a flat list of all column names reachable from this node and all descendants. |

### `LogTable` and `LogSubtable`

| Method | Description |
|---|---|
| `filter_entries(field_name, comparator, value, subtable, operation)` | Filters `cur_table` by a field value, optionally routing through a named subtable. |
| `filter_mean(field_name, comparator, value, subtable)` | Convenience wrapper for `filter_entries` with `operation='mean'`. |
| `sort_by_time(ascending)` | Sorts `cur_table` by GPS week and milliseconds. (`LogTable` only.) |
| `filter_start_time(start_time)` | Retains only rows at or after `start_time`. (`LogTable` only.) |
| `filter_end_time(end_time)` | Retains only rows at or before `end_time`. (`LogTable` only.) |
| `filter_time_range(start_time, end_time)` | Applies both start and end time filters. (`LogTable` only.) |
| `reset_filters()` | Restores `cur_table` and all descendant subtables to their unfiltered state. |
| `sort_by(field, ascending)` | Sorts `cur_table` by an arbitrary column. |
| `get_mean(field_name, group)` | Returns mean of a field, optionally grouped by `parent_id`. |
| `get_median(field_name, group)` | Returns median, optionally grouped. |
| `get_min(field_name, group)` | Returns minimum, optionally grouped. |
| `get_max(field_name, group)` | Returns maximum, optionally grouped. |
| `get_sum(field_name, group)` | Returns sum, optionally grouped. |
| `get_std(field_name, group)` | Returns standard deviation, optionally grouped. |
| `get_field_stats(field_name)` | Returns a `describe()` dict for a field, searching subtables if not found locally. |
| `get_columns()` | Returns all column names in this table and its descendants. |
| `create_log_entry(log_class, row)` | Instantiates a dynamically generated dataclass for a single row, recursing into subtables. |
| `__iter__()` | Yields a `create_log_entry` result for each row in `cur_table`. |

### `FieldValue` properties

| Property | Description |
|---|---|
| `mean` | Mean of this field across all current rows. |
| `grouped_mean` | Mean grouped by `parent_id`, returned as a `pd.Series`. |
| `median` | Median across all current rows. |
| `grouped_median` | Median grouped by `parent_id`. |
| `min` | Minimum value. |
| `grouped_min` | Minimum grouped by `parent_id`. |
| `max` | Maximum value. |
| `grouped_max` | Maximum grouped by `parent_id`. |
| `sum` | Sum of all values. |
| `grouped_sum` | Sum grouped by `parent_id`. |
| `std` | Standard deviation. |
| `grouped_std` | Standard deviation grouped by `parent_id`. |

---

## Known Limitations and Future Work

1. **No lazy loading.** Every `LogFrame` constructor calls `pd.read_parquet` unconditionally. For databases with many message types or large tables, constructing a `PqReader` loads the entire database into memory before the caller has specified any filters. The `logs` parameter partially mitigates this by restricting which subtables are instantiated, but within each loaded table all columns and rows are always read. A fully lazy variant would defer loading until first access and would enable per-column projection pushdown to the Parquet layer.

2. **Mutable `cur_table` state model.** All filter operations mutate `self.cur_table` in-place, and `reset_filters` is the only way to undo them. This design is not thread-safe: concurrent reads while a filter is being applied will observe a partially-narrowed table. It also makes it impossible to maintain multiple independent filter views of the same database simultaneously without constructing separate `PqReader` instances.
