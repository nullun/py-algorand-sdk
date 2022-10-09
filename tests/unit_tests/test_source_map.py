from copy import deepcopy
import json
from typing import List

from algosdk.source_map import (
    Chunk,
    FunctionalSourceMapper,
    SourceMap as TealSourceMap,
    JSONSourceMap,
    MJPSourceMap,
)


###### FIXTURES ######

quine_preteal = """#pragma version 5
// To modify the program:
// 1. Replace the first line with `pushbytes ""; (test)
// 2. Compile the program.
// 3. Replace the first line with `pushbytes <compiled bytecode>`
// 4. Update the varuint length of the new bytecode (line 11)
// 5. The quine is complete. Compile again.
pushbytes 0x0580004957000280011a504f0149570300505081007200441243
    dup; extract 0 2
pushbytes 0x1a // the varuint length of 0x0580...
    concat; uncover 1; dup
    extract 3 0 // the range here must be updated if the varuint length is longer than 1 byte
    concat; concat // after this line the whole program is on the stack
pushint 0
    app_params_get AppApprovalProgram; assert
==; return"""

quine_teal = """#pragma version 5
// To modify the program:
// 1. Replace the first line with `pushbytes ""; (test)
// 2. Compile the program.
// 3. Replace the first line with `pushbytes <compiled bytecode>`
// 4. Update the varuint length of the new bytecode (line 11)
// 5. The quine is complete. Compile again.
pushbytes 0x0580004957000280011a504f0149570300505081007200441243
dup
extract 0 2
pushbytes 0x1a // the varuint length of 0x0580...
concat
uncover 1
dup
extract 3 0 // the range here must be updated if the varuint length is longer than 1 byte
concat
concat // after this line the whole program is on the stack
pushint 0
app_params_get AppApprovalProgram
assert
==
return"""

quine2pc = '{"version":3,"sources":[],"names":[],"mapping":";AAOA;;;;;;;;;;;;;;;;;;;;;;;;;;;;AACA;AACA;;;AACA;;;AACA;AACA;;AACA;AACA;;;AACA;AACA;AACA;;AACA;;AACA;AACA;AACA","mappings":";AAOA;;;;;;;;;;;;;;;;;;;;;;;;;;;;AACA;AACA;;;AACA;;;AACA;AACA;;AACA;AACA;;;AACA;AACA;AACA;;AACA;;AACA;AACA;AACA"}'

# coffee examples from https://github.com/firefox-devtools/devtools-examples/blob/main/sourcemaps-in-console/js

coffee = """person = document.getElementById('person')

greet = (greeting) ->
  console.log(greeting + " " + person.value)

person.addEventListener("focus", -> person.value = "")

greetButton = document.getElementById('greet')

greetButton.addEventListener("click", () ->
  helloOption = document.querySelector("#hello")
  greeting = if helloOption.checked then "Hello" else "Goodbye"
  greet(greeting);
)"""

js = """// Generated by CoffeeScript 1.10.0
(function() {
  var greet, greetButton, person;

  person = document.getElementById('person');

  greet = function(greeting) {
    return console.log(greeting + " " + person.value);
  };

  person.addEventListener("focus", function() {
    return person.value = "";
  });

  greetButton = document.getElementById('greet');

  greetButton.addEventListener("click", function() {
    var greeting, helloOption;
    helloOption = document.querySelector("#hello");
    greeting = helloOption.checked ? "Hello" : "Goodbye";
    return greet(greeting);
  });

}).call(this);

//# sourceMappingURL=main.js.map"""

coffee2js = """{
  "version": 3,
  "file": "main.js",
  "sourceRoot": "",
  "sources": [
    "main.coffee"
  ],
  "names": [],
  "mappings": ";AAAA;AAAA,MAAA;;EAAA,MAAA,GAAS,QAAQ,CAAC,cAAT,CAAwB,QAAxB;;EAET,KAAA,GAAQ,SAAC,QAAD;WACN,OAAO,CAAC,GAAR,CAAY,QAAA,GAAW,GAAX,GAAiB,MAAM,CAAC,KAApC;EADM;;EAGR,MAAM,CAAC,gBAAP,CAAwB,OAAxB,EAAiC,SAAA;WAAG,MAAM,CAAC,KAAP,GAAe;EAAlB,CAAjC;;EAEA,WAAA,GAAc,QAAQ,CAAC,cAAT,CAAwB,OAAxB;;EAEd,WAAW,CAAC,gBAAZ,CAA6B,OAA7B,EAAsC,SAAA;AACpC,QAAA;IAAA,WAAA,GAAc,QAAQ,CAAC,aAAT,CAAuB,QAAvB;IACd,QAAA,GAAc,WAAW,CAAC,OAAf,GAA4B,OAA5B,GAAyC;WACpD,KAAA,CAAM,QAAN;EAHoC,CAAtC;AATA"
}"""

### An artificial compiler, to demonstrate composability and `FunctionalSourceMapper`


def example_pre_compile(pre_teal: str) -> List[Chunk]:
    """Example revision source chunks generator"""

    def at_comment(line: str, idx: int) -> bool:
        return idx < len(line) - 1 and line[idx] == line[idx + 1] == "/"

    tln = 0
    chunks = []
    for sln, sline in enumerate(pre_teal.split("\n")):
        next_line = False
        tline = sline
        bounds = (-1, -1)

        def collect():
            chunks.append(
                Chunk(sln, sline, bounds, tln, tline, (0, len(tline)))
            )

        # special treatment of row 0:
        if sln == 0:
            assert (
                sline[0] == "#"
            ), f"expected immediate pragma with first char '#' but got {sline[0]}"
            next_line = True

        if not next_line:
            lbound = 0
            for j, c in enumerate(sline):
                if c == ";":
                    bounds = (lbound, j)
                    tline = sline[lbound:j].strip()
                    collect()
                    lbound = j + 1
                    tln += 1
                    continue

                if j == len(sline) - 1:
                    bounds = (lbound, j + 1)
                    tline = sline[lbound : j + 1].strip()
                    collect()
                    lbound = j + 1
                    tln += 1
                    continue

                if at_comment(tline, j):
                    next_line = True
                    break

        if next_line:
            bounds = (0, len(tline))
            tline = tline.strip()
            collect()
            tln += 1
            continue

    return chunks


####### UNIT TESTS #######


def test_chunk():
    snum, source = 42, "the source"
    tnum, target = 1337, "the target"

    def bounds(s):
        return (0, len(s))

    assert Chunk(
        snum, source, bounds(source), tnum, target, bounds(target)
    ) == Chunk.simple(snum, source, tnum, target)


def source_mapper_invariants(smapper):
    assert len(smapper.chunks) == len(smapper.index)
    assert all(
        idx < smapper.index[i + 1] for i, idx in enumerate(smapper.index[:-1])
    )
    assert all(
        smapper(idx[0], idx[1] - 1) == smapper.chunks[i]
        for i, idx in enumerate(smapper.index)
    )


def construct_sourcemap():
    quine_chunks = example_pre_compile(quine_preteal)
    for chunk in quine_chunks:
        print(chunk.target_line)

    quine_precompiled, quine_sourcemapper = FunctionalSourceMapper.construct(
        quine_chunks
    )

    assert quine_teal == quine_precompiled
    assert quine_chunks == quine_sourcemapper.chunks

    source_mapper_invariants(quine_sourcemapper)
    return quine_sourcemapper


def test_compose_sourcemap():
    quine2pc_d = json.loads(quine2pc)
    pc_sourcemap = TealSourceMap(quine2pc_d)
    teal2pc_chunks = pc_sourcemap.get_chunks_with_source(quine_teal)
    teal_sourcemapper = FunctionalSourceMapper.from_chunks(teal2pc_chunks)
    source_mapper_invariants(teal_sourcemapper)

    quine_sourcemapper = construct_sourcemap()
    product_sourcemapper = teal_sourcemapper * quine_sourcemapper
    source_mapper_invariants(product_sourcemapper)

    assert teal_sourcemapper.target() == product_sourcemapper.target()
    assert len(teal_sourcemapper.chunks) == len(product_sourcemapper.chunks)


def test_i_need_coffee():
    # COFFEE:
    coffee2js_d = json.loads(coffee2js)
    # TODO: Do I still need FunctionalSourceMapper?
    coffee_mapper = FunctionalSourceMapper.from_map(coffee2js_d, source=coffee)
    coffee2js_j = JSONSourceMap(coffee2js_d)
    coffee2js_mjpsm = MJPSourceMap.from_json(
        coffee2js_j, sources=[coffee], target=js, add_right_bounds=False
    )
    coffee2js_j_re_j = coffee2js_mjpsm.to_json()
    assert "sourcesContent" in coffee2js_j_re_j
    assert "sourcesContent" not in coffee2js_j
    assert coffee2js_j_re_j.pop("sourcesContent") == [coffee]
    assert coffee2js_j == coffee2js_j_re_j

    # QUINE:
    quine2pc_d = json.loads(quine2pc)
    quine_mapper = FunctionalSourceMapper.from_map(
        quine2pc_d, source=coffee, pop_mapping=True
    )
    quine2pc_j = JSONSourceMap(quine2pc_d)
    # TODO: make compatible with previous version
    quine2pc_mjpsm = MJPSourceMap.from_json(
        quine2pc_j, sources=[quine_teal], add_right_bounds=False
    )
    quine2pc_j_re_j = quine2pc_mjpsm.to_json()
    assert "sourcesContent" in quine2pc_j_re_j
    assert "sourcesContent" not in coffee2js_j

    # empty "sourcesContent" because "content" defines it and it is erroneously empty...
    assert quine2pc_j_re_j.pop("sourcesContent") == [quine_teal]
    # remove deprecated "mapping"
    deprecated_mapping = quine2pc_j.pop("mapping")
    assert quine2pc_j_re_j["mappings"] == deprecated_mapping
    assert ["unknown"] == quine2pc_j_re_j.pop("sources")
    assert [] == quine2pc_j.pop("sources")
    assert quine2pc_j == quine2pc_j_re_j

    # Next, try and add right bounds

    # COFFEE:
    coffee_entries = deepcopy(coffee2js_mjpsm.entries)
    coffee2js_mjpsm.add_right_bounds()
    assert coffee_entries != coffee2js_mjpsm.entries
    coffee2js_mjpsm2 = MJPSourceMap.from_json(
        coffee2js_j, sources=[coffee], target=js
    )
    assert coffee2js_mjpsm.entries == coffee2js_mjpsm2.entries

    # QUINE:
    quine_entries = deepcopy(quine2pc_mjpsm.entries)
    quine2pc_mjpsm.add_right_bounds()
    # it didn't change anything B/C only infer rbounds from multiple entries on a single target line
    assert quine_entries == quine2pc_mjpsm.entries
    quine2pc_mjpsm2 = MJPSourceMap.from_json(quine2pc_j, sources=[quine_teal])
    assert quine2pc_mjpsm.entries == quine2pc_mjpsm2.entries
