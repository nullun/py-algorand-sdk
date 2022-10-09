import bisect
from copy import deepcopy
from dataclasses import dataclass
from typing import (
    Literal,
    Mapping,
    cast,
    Dict,
    Any,
    List,
    Optional,
    Iterable,
    Tuple,
    TypedDict,
)

from algosdk.error import SourceMapVersionError


# class SourceMapJSON(TypedDict, total=False):
#     version: Literal[3]
#     file: str
#     sourceRoot: Optional[str]
#     sources: List[str]
#     sourcesContent: List[Optional[str]]
#     names: List[str]
#     mappings: str


@dataclass(frozen=True)
class SourceMapJSON:
    version: Literal[3]
    sources: List[str]
    names: List[str]
    mappings: str
    file: Optional[str] = None
    sourceRoot: Optional[str] = None
    sourcesContent: Optional[List[Optional[str]]] = None


"""

{
"version" : 3,
"file": "out.js",
"sourceRoot": "",
"sources": ["foo.js", "bar.js"],
"sourcesContent": [null, null],
"names": ["src", "maps", "are", "fun"],
"mappings": "A,AAAB;;ABCDE;"
}

TODO: enable sequences of Chunk's to define a Revision 3 Source Map.
e.g cf:
* https://gist.github.com/mjpieters/86b0d152bb51d5f5979346d11005588b
* OR: https://github.com/algochoi/teal-sourcemap-decoder/blob/main/decode.py

class SourceMap:
    " ""
    More general purpose than TealSourceMap
    " ""
    def __init__(self, source_map: Dict[str, Any]):
        self.version: int = source_map["version"]
        if self.version != 3:
            raise SourceMapVersionError(self.version)

        self.file: Optional[str] = source_map.get("file")
        self.sourceRoot: Optional[str] = source_map.get("sourceRoot")
        self.sources: List[str] = source_map["sources"]
        self.sourcesContent: Optional[List[Optional[str]]] = source_map.get("sourcesContent")
        self.names: List[str] = source_map["names"]
        self.mappings: str = source_map["mappings"]


        pc_list = [
            _decode_int_value(raw_val) for raw_val in self.mappings.split(";")
        ]

        self.pc_to_line: Dict[int, int] = {}
        self.line_to_pc: Dict[int, List[int]] = {}

        last_line = 0
        for index, line_delta in enumerate(pc_list):
            # line_delta is None if the line number has not changed
            # or if the line is empty
            if line_delta is not None:
                last_line = last_line + line_delta

            if last_line not in self.line_to_pc:
                self.line_to_pc[last_line] = []

            self.line_to_pc[last_line].append(index)
            self.pc_to_line[index] = last_line
"""


class SourceMap:
    """
    Decodes a VLQ-encoded source mapping between PC values and TEAL source code lines.
    Spec available here: https://sourcemaps.info/spec.html

    Args:
        source_map (dict(str, Any)): source map JSON from algod
    """

    def __init__(self, source_map: Dict[str, Any]):

        self.version: int = source_map["version"]

        if self.version != 3:
            raise SourceMapVersionError(self.version)

        self.sources: List[str] = source_map["sources"]

        self.mappings: str = source_map["mappings"]

        pc_list = [
            _decode_int_value(raw_val) for raw_val in self.mappings.split(";")
        ]

        self.pc_to_line: Dict[int, int] = {}
        self.line_to_pc: Dict[int, List[int]] = {}

        last_line = 0
        for index, line_delta in enumerate(pc_list):
            # line_delta is None if the line number has not changed
            # or if the line is empty
            if line_delta is not None:
                last_line = last_line + line_delta

            if last_line not in self.line_to_pc:
                self.line_to_pc[last_line] = []

            self.line_to_pc[last_line].append(index)
            self.pc_to_line[index] = last_line

    def get_line_for_pc(self, pc: int) -> Optional[int]:
        return self.pc_to_line.get(pc, None)

    def get_pcs_for_line(self, line: int) -> Optional[List[int]]:
        return self.line_to_pc.get(line, None)

    def get_chunks_with_source(self, teal: str) -> List["Chunk"]:
        lines = teal.split("\n")
        assert max(self.pc_to_line.values()) < len(
            lines
        ), f"teal had {len(lines)} lines which can't accommodate the biggest expected line number {max(self.pc_to_line.values())}"

        return [
            Chunk.simple(line, lines[line], pc, f"PC[{pc}]")
            for pc, line in self.pc_to_line.items()
        ]


def _decode_int_value(value: str) -> Optional[int]:
    # Mappings may have up to 5 segments:
    # Third segment represents the zero-based starting line in the original source represented.
    decoded_value = _base64vlq_decode(value)
    return decoded_value[2] if decoded_value else None


"""
Source taken from: https://gist.github.com/mjpieters/86b0d152bb51d5f5979346d11005588b
"""

_b64chars = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_b64table = [-1] * (max(_b64chars) + 1)
for i, b in enumerate(_b64chars):
    _b64table[b] = i

shiftsize, flag, mask = 5, 1 << 5, (1 << 5) - 1


def _base64vlq_decode(vlqval: str) -> List[int]:
    """Decode Base64 VLQ value"""
    results = []
    shift = value = 0
    # use byte values and a table to go from base64 characters to integers
    for v in map(_b64table.__getitem__, vlqval.encode("ascii")):
        v = cast(int, v)
        value += (v & mask) << shift
        if v & flag:
            shift += shiftsize
            continue
        # determine sign and add to results
        results.append((value >> 1) * (-1 if value & 1 else 1))
        shift = value = 0
    return results


def _base64vlq_encode(*values: int) -> str:
    """Encode integers to a VLQ value"""
    results = []
    add = results.append
    for v in values:
        # add sign bit
        v = (abs(v) << 1) | int(v < 0)
        while True:
            toencode, v = v & mask, v >> shiftsize
            add(toencode | (v and flag))
            if not v:
                break
    return bytes(map(_b64chars.__getitem__, results)).decode()


from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    """Practical data needed for a useful source map"""

    source_line_number: int
    source_line: str
    source_col_bounds: Tuple[int, int]
    target_line_number: int
    target_line: str
    target_col_bounds: Tuple[int, int]

    def __repr__(self) -> str:
        """TODO: this is just a temporary hack"""
        sbnds, tbnds = self.source_col_bounds, self.target_col_bounds
        return (
            "\n"
            + (
                f"source({self.source_line_number}:{sbnds}) --> "
                f"target({self.target_line_number}:{tbnds})"
            )
            + "\n\t\t"
            + f"SANITY CHECK: <<{self.source_line[sbnds[0]:sbnds[1]]}>> =?= <<{self.target_line[tbnds[0]:tbnds[1]]}>>"
        )

    @classmethod
    def simple(
        cls,
        source_line_number: int,
        source_line: str,
        target_line_number: int,
        target_line: str,
    ) -> "Chunk":
        """A simple Chunk consists of an entire line, therefore, the column info is omittef"""
        return cls(
            source_line_number,
            source_line,
            (0, len(source_line)),
            target_line_number,
            target_line,
            (0, len(target_line)),
        )


class FunctionalSourceMapper:
    """
    Callable object mapping target back to original source
    """

    def __init__(
        self,
        indexer: List[Tuple[int, int]],
        chunks: List[Chunk],
        source_map: Optional[SourceMapJSON] = None,
    ):
        self.index = indexer
        self.chunks = chunks
        self.source_map: Optional[SourceMapJSON] = source_map

    @staticmethod
    def from_chunks(chunks: Iterable[Chunk]) -> "FunctionalSourceMapper":
        chunks = list(chunks)
        indexer = [
            (line, chunk.source_col_bounds[1])
            for line, chunk in enumerate(chunks)
        ]

        # TODO: these assertions probly don't belong here

        assert len(chunks) == len(indexer)
        assert all(idx < indexer[i + 1] for i, idx in enumerate(indexer[:-1]))

        fsm = FunctionalSourceMapper(indexer, chunks)
        assert all(
            fsm(idx[0], idx[1] - 1) == chunks[i]
            for i, idx in enumerate(indexer)
        )

        return fsm

    @staticmethod
    def from_map(
        m: Mapping[str, Any], source: str, pop_mapping: bool = False
    ) -> SourceMapJSON:
        if pop_mapping:
            m = {**m}
            m.pop("mapping")
        smj = SourceMapJSON(**m)

        return smj

    def __repr__(self) -> str:
        return repr(self.chunks)

    def __call__(self, line: int, column: int) -> Optional[Chunk]:
        idx = bisect.bisect_right(self.index, (line, column))
        if 0 <= idx < len(self.index):
            return self.chunks[idx]
        return None

    def __mul__(
        self, other: "FunctionalSourceMapper"
    ) -> "FunctionalSourceMapper":
        """
        Suppose we've compiled A -> B and also B -> C and that we have
        source maps acting from target to source as follows:
        - self:         C -> B
        - other:        B -> A
        then:
        self * other:   C -> A

        I.e. self * other represents the source map for the composite compilation A -> B -> C
        """
        assert isinstance(other, FunctionalSourceMapper)

        chunks = []
        for schunk in self.chunks:
            ochunk = other(
                schunk.source_line_number, schunk.source_col_bounds[0]
            )
            assert ochunk

            chunks.append(
                Chunk(
                    ochunk.source_line_number,
                    ochunk.source_line,
                    ochunk.source_col_bounds,
                    schunk.target_line_number,
                    schunk.target_line,
                    schunk.source_col_bounds,
                )
            )

        return FunctionalSourceMapper.from_chunks(chunks)

    def target(self) -> str:
        return self.generate_target(self.chunks)

    # TODO: clean up the API - probly don't need the following:

    @classmethod
    def generate_target(cls, chunks: Iterable[Chunk]) -> str:
        return "\n".join(map(lambda chunk: chunk.target_line, chunks))

    @staticmethod
    def construct(
        chunks: Iterable[Chunk],
    ) -> Tuple[str, "FunctionalSourceMapper"]:
        return FunctionalSourceMapper.generate_target(
            chunks
        ), FunctionalSourceMapper.from_chunks(chunks)


#### ---- ORIGINAL mjpieters CODE ---- ####

"""Extract generated -> source mappings"""

from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial
from itertools import count
from typing import List, Literal, Mapping, Optional, Tuple, TypedDict, Union


class autoindex(defaultdict):
    def __init__(self, *args, **kwargs):
        super().__init__(partial(next, count()), *args, **kwargs)


class JSONSourceMap(TypedDict, total=False):
    version: Literal[3]
    file: Optional[str]
    sourceRoot: Optional[str]
    sources: List[str]
    sourcesContent: Optional[List[Optional[str]]]
    names: List[str]
    mappings: str


@dataclass(frozen=True)
class SourceMapping:
    line: int
    column: int
    source: Optional[str] = None
    source_line: Optional[int] = None
    source_column: Optional[int] = None
    name: Optional[str] = None
    source_extract: Optional[str] = None
    target_extract: Optional[str] = None
    source_content: Optional[List[str]] = None

    def __post_init__(self):
        if self.source is not None and (
            self.source_line is None or self.source_column is None
        ):
            raise TypeError(
                "Invalid source mapping; missing line and column for source file"
            )
        if self.name is not None and self.source is None:
            raise TypeError(
                "Invalid source mapping; name entry without source location info"
            )

    @property
    def content_line(self) -> Optional[str]:
        try:
            # self.source_content.splitlines()[self.source_line]  # type: ignore
            self.source_content[self.source_line]  # type: ignore
        except (TypeError, IndexError):
            return None


@dataclass(frozen=True)
class MJPSourceMap:
    file: Optional[str]
    source_root: Optional[str]
    entries: Mapping[Tuple[int, int], SourceMapping]
    _index: List[Tuple[int, ...]] = field(default_factory=list)

    def __repr__(self) -> str:
        parts = []
        if self.file is not None:
            parts += [f"file={self.file!r}"]
        if self.source_root is not None:
            parts += [f"source_root={self.source_root!r}"]
        parts += [f"len={len(self.entries)}"]
        return f"<MJPSourceMap({', '.join(parts)})>"

    @classmethod
    def from_json(
        cls,
        smap: JSONSourceMap,
        sources: List[str] = [],
        source_files: Optional[List[str]] = None,
        target: Optional[str] = None,
    ) -> "MJPSourceMap":
        # TODO: the following mypy errors goes away with the dataclass
        if smap["version"] != 3:
            raise ValueError("Only version 3 sourcemaps are supported")
        entries, index = {}, []
        spos = npos = sline = scol = 0
        jsource_files = smap.get("sources")
        if not (source_files or jsource_files):
            source_files = ["unknown"]
        elif not source_files:
            source_files = jsource_files
        assert source_files

        names, contents = (
            smap.get("names"),
            smap.get("sourcesContent", sources),
        )  # type: ignore
        sp_conts = [c.splitlines() for c in contents]
        tcont = target.splitlines() if target else None
        for gline, vlqs in enumerate(smap["mappings"].split(";")):
            index += [[]]
            if not vlqs:
                continue
            gcol = 0
            for gcd, *ref in map(_base64vlq_decode, vlqs.split(",")):
                gcol += gcd
                kwargs = {}
                if len(ref) >= 3:
                    sd, sld, scd, *namedelta = ref
                    spos, sline, scol = spos + sd, sline + sld, scol + scd
                    # scont = contents[spos] if len(contents) > spos else None  # type: ignore
                    scont = sp_conts[spos] if len(sp_conts) > spos else None  # type: ignore
                    # extract the referenced source till the end of the current line
                    scont_extract = scont[sline][scol:] if scont else None
                    tcont_extract = tcont[gline][gcol:] if tcont else None
                    kwargs = {
                        "source": source_files[spos]
                        if spos < len(source_files)
                        else None,
                        "source_line": sline,
                        "source_column": scol,
                        "source_content": scont,
                        "source_extract": scont_extract,
                        "target_extract": tcont_extract,
                    }
                    if namedelta:
                        npos += namedelta[0]
                        kwargs["name"] = names[npos]
                entries[gline, gcol] = SourceMapping(
                    line=gline, column=gcol, **kwargs
                )
                index[gline].append(gcol)

        return cls(
            smap.get("file"),
            smap.get("sourceRoot"),
            entries,
            [tuple(cs) for cs in index],
        )

    def to_json(self) -> JSONSourceMap:
        content, mappings = [], []
        sources, names = autoindex(), autoindex()
        entries = self.entries
        spos = sline = scol = npos = 0
        for gline, cols in enumerate(self._index):
            gcol = 0
            mapping = []
            for col in cols:
                entry = entries[gline, col]
                ds, gcol = [col - gcol], col

                if entry.source is not None:
                    assert entry.source_line is not None
                    assert entry.source_column is not None
                    ds += (
                        sources[entry.source] - spos,
                        entry.source_line - sline,
                        entry.source_column - scol,
                    )
                    spos, sline, scol = (
                        spos + ds[1],
                        sline + ds[2],
                        scol + ds[3],
                    )
                    if spos == len(content):
                        c = entry.source_content
                        content.append("\n".join(c) if c else None)
                    if entry.name is not None:
                        ds += (names[entry.name] - npos,)
                        npos += ds[-1]
                mapping.append(_base64vlq_encode(*ds))

            mappings.append(",".join(mapping))

        encoded = {
            "version": 3,
            "sources": [
                s for s, _ in sorted(sources.items(), key=lambda si: si[1])
            ],
            "sourcesContent": content,
            "names": [
                n for n, _ in sorted(names.items(), key=lambda ni: ni[1])
            ],
            "mappings": ";".join(mappings),
        }
        if self.file is not None:
            encoded["file"] = self.file
        if self.source_root is not None:
            encoded["sourceRoot"] = self.source_root
        return encoded  # type: ignore

    def __getitem__(self, idx: Union[int, Tuple[int, int]]):
        try:
            l, c = idx  # type: ignore
        except TypeError:
            l, c = idx, 0
        try:
            return self.entries[l, c]  # type: ignore
        except KeyError:
            # find the closest column
            if not (cols := self._index[l]):  # type: ignore
                raise IndexError(idx)
            cidx = bisect.bisect(cols, c)
            return self.entries[l, cols[cidx and cidx - 1]]  # type: ignore
