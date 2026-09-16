#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
################################################################################

MIT License

Copyright (c) 2026 NovAtel Inc.

This project is licensed under the MIT License. A copy of the license is
available in the LICENSE file included with this repository.

This software may incorporate or depend upon third-party software components
that are subject to separate license terms. Users are responsible for
complying with any applicable third-party licenses.

NovAtel® and other product names, logos, and trademarks referenced in this
project are the property of their respective owners. No rights or licenses to
NovAtel trademarks are granted under the MIT License.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, AS MORE FULLY SET FORTH IN THE LICENSE FILE.
################################################################################

Public read API for a nov_gnsspq Parquet database.

Provides :class:`PqReader` as the top-level entry point.  The hierarchy
mirrors the on-disk directory layout::

    PqReader           (root - one row per message in the recording)
    └── LogTable    (one per log type, e.g. BESTPOS, RANGE)
        └── LogSubtable  (one per nested message field group)

Filtering, sorting, time-range queries, and summary statistics are available
at every level.  :class:`FieldValue` offers a per-column property shorthand
for the most common aggregations.
"""

from __future__ import annotations

import dataclasses
import datetime
import operator as _op
import os
import tempfile
import zipfile as _zipfile
from pathlib import Path
from typing import Any, Callable, Type

import pandas as pd
from nov_gnsspq.compat.gpstime import GPSTime
from nov_gnsspq.compat.telemetry import start_as_auto_span, telemetry
from nov_gnsspq.exceptions import FieldNotFoundError

# Handle pandas version compatibility
try:
    from pandas.api.typing import SeriesGroupBy
except ImportError:
    from pandas.core.groupby import SeriesGroupBy

__all__ = [
    "PqReader",
    "LogTable",
    "LogSubtable",
    "FieldValue",
]

tracer = telemetry.get_tracer(__name__)

# ---------------------------------------------------------------------------
# Module-level dispatch tables
# ---------------------------------------------------------------------------

_SUMMARY_OPS: dict[str, Callable] = {
    'mean': lambda obj: obj.mean(),
    'median': lambda obj: obj.median(),
    'min': lambda obj: obj.min(),
    'max': lambda obj: obj.max(),
    'sum': lambda obj: obj.sum(),
    'std': lambda obj: obj.std(),
    'rms': lambda obj: ((obj ** 2).mean() ** 0.5),
}

_COMPARATORS: dict[str, Callable] = {
    '==': _op.eq,
    '!=': _op.ne,
    '<':  _op.lt,
    '<=': _op.le,
    '>':  _op.gt,
    '>=': _op.ge,
}


# ---------------------------------------------------------------------------
# Schema configuration
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class SchemaConfig:
    """Column-name mapping for the database schema."""

    week_col: str
    milliseconds_col: str
    sequence_id_col: str

    @property
    def time_columns(self) -> list[str]:
        """time_columns: The week and milliseconds column names as a list."""
        return [self.week_col, self.milliseconds_col]


_SCHEMA = SchemaConfig(
    week_col="header_week",
    milliseconds_col="header_milliseconds",
    sequence_id_col="sequence_id",
)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

class Utils:
    """Utility helpers for the log database."""

    @staticmethod
    def convert_time_format(time: datetime.datetime | GPSTime) -> GPSTime:
        """Convert time to GPSTime.

        Args:
            time: The time to convert.  May be a :class:`datetime.datetime`
                or a :class:`GPSTime`.

        Returns:
            The converted GPSTime instance; GPSTime inputs are returned
            unchanged.
        """
        if isinstance(time, datetime.datetime):
            return GPSTime(time)
        return time

    @classmethod
    def _stringify_tree_recursive(
            cls, tree: dict, prefix: str, string: str) -> str:
        """Create string for a branch of a tree structure.

        Args:
            tree: A dictionary whose keys represent the tree.
            prefix: The prefix to add to the string, based on depth.
            string: The string to add to.

        Returns:
            The input string with a representation of the branch appended.
        """
        children = list(tree.items())
        for idx, (key, value) in enumerate(children):
            is_last = idx == len(children) - 1
            if isinstance(value, dict):
                subtree_prefix = '│   ' if not is_last else '    '
                string += (
                    f'{prefix}├── {key}\n' if not is_last
                    else f'{prefix}└── {key}\n')
                string = cls._stringify_tree_recursive(
                    value, prefix + subtree_prefix, string)
            else:
                string += (
                    f'{prefix}├── {value}\n' if not is_last
                    else f'{prefix}└── {value}\n')
        return string

    @classmethod
    def stringify_tree(cls, tree: dict) -> str:
        """Create a formatted tree structure from a dictionary spec.

        Args:
            tree: A dictionary whose keys represent the tree.  Example::

                    {'root':
                        {'branch1':
                            {'leaf1': {},
                             'leaf2': {}},
                         'branch2': {}}

        Returns:
            The formatted tree string.
        """
        trunk = list(tree.items())[0]
        string = f'{trunk[0]}\n'
        children = list(trunk[1].items())
        for idx, (key, value) in enumerate(children):
            is_last = idx == len(children) - 1
            subtree_prefix = '│   ' if not is_last else '    '
            string += (
                f'├── {key}\n' if not is_last
                else f'└── {key}\n')
            string = cls._stringify_tree_recursive(
                value, subtree_prefix, string)
        return string


# ---------------------------------------------------------------------------
# Core frame classes
# ---------------------------------------------------------------------------

class LogFrame:
    """A frame/table of log data with references to subframes/tables."""

    def __init__(
            self,
            table_name: str,
            folder_path: str,
            parent: 'LogFrame | None' = None,
            schema: SchemaConfig = _SCHEMA,
            logs: list[str] | None = None):
        """Initializes the LogFrame.

        Args:
            table_name: The name of the table.
            folder_path: The path to the folder containing the table data.
            parent: The parent table.
            schema: Column-name mapping for this database's schema version.
            logs: If given, only the named log types are loaded.
        """
        self.table_name = table_name
        self.folder_path = folder_path
        self._schema = schema
        self._subtables = self._get_subtables()
        path = os.path.join(self.folder_path, f'{table_name}.parquet')

        if logs is not None:
            self.table = pd.read_parquet(
                path, filters=[('log', 'in', logs)])
        else:
            self.table = pd.read_parquet(path)
        self.cur_table = self.table
        self.parent = parent
        self.subtables = self._get_subtable_class()

    @property
    def _child_type(self) -> Type:
        """_child_type: The type of any subtables."""
        return LogTable

    def _get_subtables(self) -> dict:
        """Returns a dict of subtables based on data from the filesystem.

        Returns:
            A dictionary mapping subtable name to subtable instance.
        """
        folder_contents = os.listdir(self.folder_path)
        subtable_names = [
            name for name in folder_contents
            if os.path.isdir(os.path.join(self.folder_path, name))]

        subtables = {}
        for subtable_name in subtable_names:
            path = os.path.join(self.folder_path, subtable_name)
            subtables[subtable_name] = self._child_type(
                subtable_name, path, self, schema=self._schema)
        return subtables

    def _get_subtable_class(self) -> Type:
        """Returns a dataclass with an attribute for each subtable.

        Returns:
            A dataclass instance with one attribute per subtable.
        """
        subtable_names = self._subtables.keys()
        subtable_class = dataclasses.make_dataclass(
            'Subtables',
            [(name, self._child_type) for name in subtable_names])

        def get_str_repr(self):
            contents = ', '.join(subtable_names)
            return f'[{contents}]'

        subtable_class.__repr__ = get_str_repr
        return subtable_class(**self._subtables)

    def get_columns(self) -> list[str]:
        """Returns a list of all columns in the table and subtables.

        Returns:
            A list of all column names across the table and its subtables.
        """
        columns = self.table.columns.tolist()
        for subtable in self._subtables.values():
            sub_columns = subtable.get_columns()
            if sub_columns is not None:
                columns.extend(sub_columns)
        return columns

    def _check_time_info(self):
        """Checks if the table contains time information.

        Raises:
            FieldNotFoundError: If the table does not contain time information.
        """
        week_col = self._schema.week_col
        ms_col = self._schema.milliseconds_col
        if (week_col not in self.cur_table.columns
                or ms_col not in self.cur_table.columns):
            raise FieldNotFoundError(
                'This table does not contain adequate information '
                'to filter by time.')

    def _get_tree(self) -> dict:
        """Returns a tree representation of the table and subtables.

        Returns:
            A dictionary representing the table structure.
        """
        rep = (f'{self.table_name} - '
               f'[{len(self)} entries, '
               f'{len(self.table.columns)} fields]')
        tree = {rep: {}}
        for subtable_obj in self._subtables.values():
            tree[rep].update(subtable_obj._get_tree())
        return tree

    def __len__(self) -> int:
        """Returns the number of entries in the table."""
        return len(self.cur_table)

    def __repr__(self) -> str:
        """Returns a formatted tree string describing the table hierarchy."""
        tree = self._get_tree()
        return Utils.stringify_tree(tree)


class PqReader(LogFrame):
    """A database of log data."""

    # TODO: Add a backend="polars" parameter for Polars DataFrame support.

    @start_as_auto_span(tracer=tracer)
    def __init__(self, db_path: str | Path, logs: list[str] | None = None):
        """Initializes the PqReader.

        Args:
            db_path: Path to the database directory, or to a ``.gnsspq``
                or ``.zip`` archive produced by
                :func:`~nov_gnsspq.writer.generator.zip_database`.  When an
                archive path is given it is extracted to a temporary
                directory for the lifetime of this instance.
            logs: If given, only the named log types are loaded.
        """
        db_path = str(db_path)
        self._tmpdir = None
        if db_path.endswith(('.gnsspq', '.zip')):
            self._tmpdir = tempfile.TemporaryDirectory()
            with _zipfile.ZipFile(db_path) as zf:
                zf.extractall(self._tmpdir.name)
            stem = os.path.splitext(os.path.basename(db_path))[0]
            db_path = os.path.join(self._tmpdir.name, stem)
        _, name = os.path.split(db_path)
        # must be set before super().__init__ calls _get_subtables
        self._logs = logs
        super().__init__(name, db_path, schema=_SCHEMA, logs=logs)
        try:
            self.unknown_table = pd.read_parquet(
                os.path.join(self.folder_path, 'unknown_data.parquet'))
        except FileNotFoundError:
            pass

    def close(self):
        """Releases resources held by this reader.

        Cleans up the temporary directory created when opening a ``.zip``
        archive.  Safe to call multiple times.
        """
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

    def __enter__(self) -> "PqReader":
        """Returns self to support use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Calls close() on exit."""
        self.close()
        return False

    def filter_by_log(self, log_name: str):
        """Filters the database by log type.

        Args:
            log_name: The name of the log to filter by.

        Raises:
            FieldNotFoundError: If the log column is absent or log_name is
                not present in the table.
        """
        if 'log' not in self.cur_table.columns:
            raise FieldNotFoundError(
                "log table does not contain a 'log' column")
        available = set(self.cur_table['log'].unique())
        if log_name not in available:
            raise FieldNotFoundError(
                f"Log type '{log_name}' not found. "
                f"Available: {sorted(available)}")
        self.cur_table = self.cur_table[self.cur_table['log'] == log_name]

    def reset_filters(self):
        """Removes all filters on the database."""
        self.cur_table = self.table
        for subtable in self._subtables.values():
            subtable.reset_filters()

    def sort_by_time(self):
        """Sorts all logs in the database by time."""
        week_col = self._schema.week_col
        ms_col = self._schema.milliseconds_col
        seq_col = self._schema.sequence_id_col

        time_chunks = []
        for subtable in self._subtables.values():
            if {week_col, ms_col, seq_col}.issubset(subtable.table.columns):
                time_chunks.append(subtable.table[[seq_col, week_col, ms_col]])

        if not time_chunks:
            return

        time_df = pd.concat(time_chunks, ignore_index=True).sort_values(
            [week_col, ms_col])
        order = {seq_id: i for i, seq_id in enumerate(time_df[seq_col])}
        n = len(order)
        sort_pos = self.cur_table[seq_col].map(order).fillna(n).astype(int)
        self.cur_table = self.cur_table.iloc[sort_pos.argsort().to_numpy()]

    def _get_subtables(self) -> dict:
        """Override to gate subdirectory instantiation by the logs filter."""
        folder_contents = os.listdir(self.folder_path)
        subtable_names = [
            name for name in folder_contents
            if os.path.isdir(os.path.join(self.folder_path, name))]

        if self._logs is not None:
            subtable_names = [n for n in subtable_names if n in self._logs]

        subtables = {}
        for subtable_name in subtable_names:
            path = os.path.join(self.folder_path, subtable_name)
            subtables[subtable_name] = self._child_type(
                subtable_name, path, self, schema=self._schema)
        return subtables

    def __iter__(self):
        """Iterate through each log entry in the database.

        Takes into account any filters applied.

        Yields:
            A tuple of (log_name, log_class_instance) for each row in
            cur_table.

        Raises:
            ValueError: If no subtable entries are found for a sequence id.
        """
        seq_col = self._schema.sequence_id_col
        for row in self.cur_table.iterrows():
            row = row[1].to_dict()
            seq_id = row[seq_col]
            log_name = row['log']
            log_table_i = self._subtables[log_name]

            mask = log_table_i.cur_table[seq_col] == seq_id
            log_table_for_index = log_table_i.cur_table[mask]

            if len(log_table_for_index) == 0:
                raise ValueError(
                    f'No subtable entries found for '
                    f'{seq_col}={seq_id}')

            # Pass as Series so create_log_entry gets {col: val}
            log_table_for_index = log_table_for_index.iloc[0]

            log_class = log_table_i.log_data_class
            log_class_instance = log_table_i.create_log_entry(
                log_class, log_table_for_index)
            yield log_name, log_class_instance


class LogTableFrame(LogFrame):
    """Any table in a log database."""

    def __init__(
            self,
            table_name: str,
            folder_path: str,
            parent: LogFrame | None = None,
            schema: SchemaConfig = _SCHEMA):
        """Initializes the LogTableFrame.

        Args:
            table_name: The name of the table.
            folder_path: The path to the folder containing the table data.
            parent: The parent of the table.
            schema: Column-name mapping for this database's schema version.
        """
        super().__init__(table_name, folder_path, parent, schema=schema)
        self.log_data_class = self.create_log_data_class()
        for field in self.fields:
            setattr(self, field, FieldValue(field, self))

    @property
    def fields(self) -> list[str]:
        """
        fields: All fields in the table, excluding the sequence id column.
        """
        return list(
            set(self.cur_table.columns) - {self._schema.sequence_id_col})

    def apply_filter_mask(self, mask: pd.Series):
        """Applies a filter mask to the table and to its subtables.

        Args:
            mask: The boolean mask to apply.
        """
        self.cur_table = self.cur_table[mask]
        seq_col = self._schema.sequence_id_col
        for subtable_obj in self._subtables.values():
            subtable_obj._filter_down(self.cur_table[seq_col])

    def create_log_data_class(self, name_prefix: str = 'LogEntry') -> Type:
        """Creates a dataclass for an entry in the table.

        Includes slots for each field and subtable.

        Args:
            name_prefix: The prefix to add to the class name.

        Returns:
            A dynamically constructed dataclass for the log.
        """
        subtable_fields = []
        for subtable in self._subtables.values():
            subtable_class = subtable.create_log_data_class(
                f'{name_prefix}{self.table_name}')
            subtable_fields.append(
                (f'{subtable.table_name}', subtable_class))

        regular_fields = list(zip(
            self.cur_table.columns, self.cur_table.dtypes))
        fields = regular_fields + subtable_fields
        return dataclasses.make_dataclass(
            f'{name_prefix}{self.table_name}', fields)

    def create_log_entry(
            self,
            log_class: Type,
            row: tuple[pd.Index, pd.Series]) -> Any:
        """Create a log entry from a row in the table.

        Args:
            log_class: The dataclass for the log.
            row: The row in the table, as a Series or (index, Series) tuple.

        Returns:
            An instance of log_class populated with data from the row.
        """
        if isinstance(row, tuple):
            row = row[1]
        row_dict = row.to_dict()
        seq_col = self._schema.sequence_id_col
        seq_id = row_dict[seq_col]

        for subtable in self._subtables.values():
            subtable_class = log_class.__dataclass_fields__[
                subtable.table_name].type

            subtable_rows = subtable.cur_table[
                subtable.cur_table['parent_id'] == seq_id]
            if len(subtable_rows) == 0:
                row_dict[subtable.table_name] = None
                continue

            if isinstance(subtable_rows, pd.Series):
                row_dict[subtable.table_name] = subtable.create_log_entry(
                    subtable_class, subtable_rows)
            else:
                row_dict[subtable.table_name] = [
                    subtable.create_log_entry(subtable_class, subtable_row)
                    for subtable_row in subtable_rows.iterrows()
                ]

        return log_class(**row_dict)

    def filter_entries(
            self,
            field_name: str,
            comparator: str,
            value: Any,
            subtable: str | tuple[str] | None = None,
            operation: str | Callable | None = None):
        """Filters the table based on a field value.

        Args:
            field_name: The field to filter by.
            comparator: The comparison operator.
            value: The value to compare to.
            subtable: The subtable to filter by.
            operation: The aggregation operation to apply to grouped data.

        Raises:
            FieldNotFoundError: If field_name is not found in this table or
                any of its subtables.
        """
        seq_col = self._schema.sequence_id_col

        if subtable:
            if isinstance(subtable, str):
                subtable = (subtable,)

            subtable_obj = self._subtables[subtable[0]]
            ids = subtable_obj._filter_by_subtable(
                field_name, value, comparator, operation, subtable[1:])
            self.cur_table = self.cur_table[
                self.cur_table[seq_col].isin(ids)]
            for subtable_obj in self._subtables.values():
                subtable_obj._filter_down(self.cur_table[seq_col])
            return

        if field_name in self.table.columns:
            cmp_fn = _COMPARATORS.get(comparator)
            if cmp_fn is None:
                raise ValueError(f'Unknown comparator: {comparator!r}')
            self.cur_table = self.cur_table[cmp_fn(self.cur_table[field_name], value)]
            for subtable_obj in self._subtables.values():
                subtable_obj._filter_down(self.cur_table[seq_col])
            return

        for subtable_obj in self._subtables.values():
            if field_name in subtable_obj.table.columns:
                raise FieldNotFoundError(
                    f'Field {field_name} not in {self.table_name} table, '
                    f"but found in the sub-table "
                    f"'{subtable_obj.table_name}'. "
                    f'Try using filter_entries('
                    f"'{field_name}', '{comparator}', {value}, "
                    f"'{subtable_obj.table_name}').")

        raise FieldNotFoundError(
            f'Field {field_name} not found in table {self.table_name} '
            'or any of its subtables')

    def filter_mean(
            self,
            field_name: str,
            comparator: str,
            value: int,
            subtable: str):
        """Filters table entries based on the mean of a field in a subtable.

        Args:
            field_name: The field to filter by.
            comparator: The comparison operator.
            value: The value to compare to.
            subtable: The subtable to retrieve related entries from.

        Raises:
            FieldNotFoundError: If the field is not found.
        """
        self.filter_entries(field_name, comparator, value, subtable, 'mean')

    def get_field_stats(self, field_name: str) -> dict | None:
        """Returns a dictionary of statistics for a field.

        Args:
            field_name: The field to get statistics for.

        Returns:
            A dictionary of descriptive statistics, or None if the field
            is not found anywhere in the hierarchy.
        """
        if field_name in self.table.columns:
            return self.table[field_name].describe().to_dict()
        for subtable in self._subtables.values():
            stats = subtable.get_field_stats(field_name)
            if stats is not None:
                return stats
        return None

    def get_max(
            self,
            field_name: str,
            group: bool = False) -> int | float | pd.Series:
        """Gets the maximum value of the field.

        Args:
            field_name: The field to get the maximum for.
            group: Whether to get the maximum by group.

        Returns:
            The maximum value of the field, or maximum value per group when
            group=True.
        """
        return self._get_summary_stats(field_name, group, 'max')

    def get_mean(
            self,
            field_name: str,
            group: bool = False) -> float | pd.Series:
        """Gets the mean value of the field.

        Args:
            field_name: The field to get the mean for.
            group: Whether to get the mean by group.

        Returns:
            The mean value of the field, or mean value per group when
            group=True.
        """
        return self._get_summary_stats(field_name, group, 'mean')

    def get_median(
            self,
            field_name: str,
            group: bool = False) -> float | pd.Series:
        """Gets the median value of the field.

        Args:
            field_name: The field to get the median for.
            group: Whether to get the median by group.

        Returns:
            The median value of the field, or median value per group when
            group=True.
        """
        return self._get_summary_stats(field_name, group, 'median')

    def get_min(
            self,
            field_name: str,
            group: bool = False) -> int | float | pd.Series:
        """Gets the minimum value of the field.

        Args:
            field_name: The field to get the minimum for.
            group: Whether to get the minimum by group.

        Returns:
            The minimum value of the field, or minimum value per group when
            group=True.
        """
        return self._get_summary_stats(field_name, group, 'min')

    def get_rms(
            self,
            field_name: str,
            group: bool = False) -> float | pd.Series:
        """Gets the root mean square of values in the field.

        Args:
            field_name: The field to get the RMS for.
            group: Whether to get the RMS by group.

        Returns:
            The RMS of values in the field, or RMS per group when group=True.
        """
        return self._get_summary_stats(field_name, group, 'rms')

    def get_std(
            self,
            field_name: str,
            group: bool = False) -> float | pd.Series:
        """Gets the standard deviation of values in the field.

        Args:
            field_name: The field to get the standard deviation for.
            group: Whether to get the standard deviation by group.

        Returns:
            The standard deviation of values in the field, or std per group
            when group=True.
        """
        return self._get_summary_stats(field_name, group, 'std')

    def get_sum(
            self,
            field_name: str,
            group: bool = False) -> int | float | pd.Series:
        """Gets the sum of values in the field.

        Args:
            field_name: The field to get the sum for.
            group: Whether to get the sum by group.

        Returns:
            The sum of values in the field, or sum per group when group=True.
        """
        return self._get_summary_stats(field_name, group, 'sum')

    def reset_filters(self):
        """Removes all filters on the table and its subtables."""
        self.cur_table = self.table
        for subtable in self._subtables.values():
            subtable.reset_filters()
        if self.parent:
            seq_col = self._schema.sequence_id_col
            parent_col = 'parent_id'
            # Only filter down when the parent exposes a sequence id column
            # and this table has a parent_id column to match against.
            # Top-level LogTable nodes lack a parent_id column.
            has_parent_seq = seq_col in self.parent.cur_table.columns
            has_parent_id = parent_col in self.cur_table.columns
            if has_parent_seq and has_parent_id:
                parent_ids = self.parent.cur_table[seq_col]
                self._filter_down(parent_ids)

    def sort_by(self, field: str, ascending: bool = True):
        """Sorts the table by a specified field.

        Args:
            field: The field to sort by.
            ascending: Whether to sort in ascending order.

        Raises:
            FieldNotFoundError: If field is not a column in the table.
        """
        if field not in self.cur_table.columns:
            raise FieldNotFoundError(
                f'Field {field} not found in table {self.table_name}')
        self.cur_table = self.cur_table.sort_values(
            field, ascending=ascending)

    def _apply_summary_op(
            self,
            pandas_obj: pd.Series | SeriesGroupBy,
            operation: str) -> float | pd.Series:
        """Applies a summary operation to the data.

        Args:
            pandas_obj: The pandas object to apply the operation to.
            operation: The operation name (e.g. 'mean', 'max').

        Returns:
            The result of the operation.

        Raises:
            ValueError: If operation is not a recognised summary operation.
        """
        op_fn = _SUMMARY_OPS.get(operation)
        if op_fn is None:
            raise ValueError(f'Unknown summary operation: {operation!r}')
        return op_fn(pandas_obj)

    def _filter_by_subtable(
            self,
            field_name: str,
            value: Any,
            comparator: str,
            operation: str | Callable[[pd.Series], Any],
            subtable: tuple[str]) -> pd.Series:
        """Retrieve a list of allowable ids based on a subtable filter.

        Args:
            field_name: The column to filter by.
            value: The value to compare to.
            comparator: The comparison operator string.
            operation: The aggregation operation to apply to the column, or
                None to compare raw values.
            subtable: Remaining subtable path components.

        Returns:
            A Series of allowable sequence ids.

        Raises:
            ValueError: If comparator is not a recognised operator string.
        """
        seq_col = self._schema.sequence_id_col

        if subtable:
            subtable_obj = self._subtables[subtable[0]]
            ids = subtable_obj._filter_by_subtable(
                field_name, value, comparator, operation, subtable[1:])
            table = self.cur_table[self.cur_table[seq_col].isin(ids)]
            return table[seq_col]

        if operation:
            groups = self.table.groupby('parent_id')[field_name]
            series_data = groups.apply(operation)

            cmp_fn = _COMPARATORS.get(comparator)
            if cmp_fn is None:
                raise ValueError(f'Unknown comparator: {comparator!r}')
            results = series_data[cmp_fn(series_data, value)]
            return results.index

        cmp_fn = _COMPARATORS.get(comparator)
        if cmp_fn is None:
            raise ValueError(f'Unknown comparator: {comparator!r}')
        return self.cur_table[cmp_fn(self.cur_table[field_name], value)]['parent_id']

    def _filter_down(self, parent_ids: pd.Series):
        """Filters the table based on parent ids.

        Args:
            parent_ids: The parent ids to filter by.
        """
        seq_col = self._schema.sequence_id_col
        self.cur_table = self.cur_table[
            self.cur_table['parent_id'].isin(parent_ids)]
        for subtable in self._subtables.values():
            subtable._filter_down(self.cur_table[seq_col])

    def _get_summary_stats(
            self,
            field_name: str,
            group: bool,
            operation: str) -> int | float | pd.Series:
        """Returns the requested statistic for the column.

        Args:
            field_name: The field to get statistics for.
            group: Whether to group by parent_id before aggregating.
            operation: The aggregation operation name.

        Returns:
            The requested statistic, either a scalar or a grouped Series.

        Raises:
            FieldNotFoundError: If field_name is not found in this table or
                any of its subtables.
        """
        if field_name in self.cur_table.columns:
            if group:
                groups = self.cur_table.groupby('parent_id')[field_name]
                stats = self._apply_summary_op(groups, operation)
                stats.index.name = f'{self.parent.table_name} index'
                return stats
            return self._apply_summary_op(
                self.cur_table[field_name], operation)

        for subtable in self._subtables.values():
            try:
                return subtable._get_summary_stats(
                    field_name, group, operation)
            except FieldNotFoundError:
                continue

        raise FieldNotFoundError(
            f'Field {field_name} not found in table {self.table_name} '
            'or any of its subtables')

    def __iter__(self):
        """Iterate through each log entry in the table.

        Yields:
            A log entry dataclass instance for each row in cur_table.
        """
        for row in self.cur_table.iterrows():
            yield self.create_log_entry(self.log_data_class, row)


class LogTable(LogTableFrame):
    """A top-level log type table in a log database."""

    @property
    def _child_type(self) -> Type:
        """_child_type: The type of any subtables."""
        return LogSubtable

    @property
    def time_range(self) -> tuple[GPSTime, GPSTime]:
        """time_range: The time range of the table.

        Raises:
            FieldNotFoundError: If the table does not contain time columns.
        """
        self._check_time_info()
        week_col = self._schema.week_col
        ms_col = self._schema.milliseconds_col
        sorted_table = self.cur_table.sort_values([week_col, ms_col])
        start_time = GPSTime(
            float(sorted_table.iloc[0][ms_col] / 1000),
            int(sorted_table.iloc[0][week_col]))
        end_time = GPSTime(
            float(sorted_table.iloc[-1][ms_col] / 1000),
            int(sorted_table.iloc[-1][week_col]))
        return start_time, end_time

    def filter_end_time(self, end_time: datetime.datetime | GPSTime):
        """Filters the table to only include entries at or before a time.

        Args:
            end_time: The time to filter to.

        Raises:
            FieldNotFoundError: If the table does not contain time columns.
        """
        self._check_time_info()
        end_time = Utils.convert_time_format(end_time)
        week_col = self._schema.week_col
        ms_col = self._schema.milliseconds_col
        ms = end_time.seconds * 1000
        before_week = self.cur_table[week_col] < end_time.week
        during_week = self.cur_table[week_col] == end_time.week
        before_milliseconds = self.cur_table[ms_col] <= ms
        mask = before_week | (during_week & before_milliseconds)
        self.apply_filter_mask(mask)

    def filter_start_time(self, start_time: datetime.datetime | GPSTime):
        """Filters the table to only include entries at or after a time.

        Args:
            start_time: The time to filter from.

        Raises:
            FieldNotFoundError: If the table does not contain time columns.
        """
        self._check_time_info()
        start_time = Utils.convert_time_format(start_time)
        week_col = self._schema.week_col
        ms_col = self._schema.milliseconds_col
        ms = start_time.seconds * 1000
        after_week = self.cur_table[week_col] > start_time.week
        during_week = self.cur_table[week_col] == start_time.week
        after_milliseconds = self.cur_table[ms_col] >= ms
        mask = after_week | (during_week & after_milliseconds)
        self.apply_filter_mask(mask)

    def filter_time_range(
            self,
            start_time: datetime.datetime | GPSTime,
            end_time: datetime.datetime | GPSTime):
        """Filters the table to only include entries within a time range.

        Args:
            start_time: The start of the time range.
            end_time: The end of the time range.
        """
        self.filter_start_time(start_time)
        self.filter_end_time(end_time)

    def sort_by_time(self, ascending: bool = True):
        """Sorts the table by time.

        Args:
            ascending: Whether to sort in ascending order.

        Raises:
            FieldNotFoundError: If the table does not contain time columns.
        """
        self._check_time_info()
        time_cols = self._schema.time_columns
        self.cur_table = self.cur_table.sort_values(
            time_cols, ascending=ascending)


class LogSubtable(LogTableFrame):
    """A subtable in a log database."""

    @property
    def _child_type(self) -> Type:
        """_child_type: The type of any subtables."""
        return LogSubtable


class FieldValue:
    """The values of a field in a log database."""

    def __init__(self, field_name: str, table: LogTableFrame):
        """Initializes the FieldValue.

        Args:
            field_name: The name of the field.
            table: The table containing the field.
        """
        self.name = field_name
        self._table = table

    @property
    def grouped_max(self) -> pd.Series:
        """grouped_max: The maximum value of the field grouped by parent_id."""
        return self._table.get_max(self.name, group=True)

    @property
    def grouped_mean(self) -> pd.Series:
        """grouped_mean: The mean value of the field grouped by parent_id."""
        return self._table.get_mean(self.name, group=True)

    @property
    def grouped_median(self) -> pd.Series:
        """
        grouped_median: The median value of the field grouped by parent_id.
        """
        return self._table.get_median(self.name, group=True)

    @property
    def grouped_min(self) -> pd.Series:
        """grouped_min: The minimum value of the field grouped by parent_id."""
        return self._table.get_min(self.name, group=True)

    @property
    def grouped_rms(self) -> pd.Series:
        """grouped_rms: The RMS of the field grouped by parent_id."""
        return self._table.get_rms(self.name, group=True)

    @property
    def grouped_std(self) -> pd.Series:
        """
        grouped_std: The standard deviation of the field grouped by parent_id.
        """
        return self._table.get_std(self.name, group=True)

    @property
    def grouped_sum(self) -> pd.Series:
        """grouped_sum: The sum of values in the field grouped by parent_id."""
        return self._table.get_sum(self.name, group=True)

    @property
    def max(self) -> int | float:
        """max: The maximum value of the field."""
        return self._table.get_max(self.name)

    @property
    def mean(self) -> float:
        """mean: The mean value of the field."""
        return self._table.get_mean(self.name)

    @property
    def median(self) -> float:
        """median: The median value of the field."""
        return self._table.get_median(self.name)

    @property
    def min(self) -> int | float:
        """min: The minimum value of the field."""
        return self._table.get_min(self.name)

    @property
    def rms(self) -> float:
        """rms: The root mean square of values in the field."""
        return self._table.get_rms(self.name)

    @property
    def std(self) -> float:
        """std: The standard deviation of values in the field."""
        return self._table.get_std(self.name)

    @property
    def sum(self) -> int | float:
        """sum: The sum of values in the field."""
        return self._table.get_sum(self.name)

    def __repr__(self) -> str:
        """Returns the string representation of the column data."""
        return str(self._table.cur_table[self.name])
