# Demos

A collection of small, self-contained demos, kept in one repository rather than
scattered across several. Each demo lives in its own top-level folder with its
own README and its own dependencies; nothing is shared between them.

| Demo | What it shows |
| --- | --- |
| [`blender-codeshade-demo/`](blender-codeshade-demo/) | Headless Blender rendering: plastic and glass materials on primitives, with shader node graphs, lighting and render settings built entirely in Python. Includes a Cycles vs EEVEE comparison of what ray tracing actually buys you. |
| [`blender-procmesh-demo/`](blender-procmesh-demo/) | Headless Blender *modelling*: a lighthouse and the rock it stands on, built from profiles, lathes, booleans and noise functions rather than by hand. One definition rendered low-poly and refined, a sheet of the twelve modelling operations, and an honest account of where a GUI modeller is still the better tool. |
| [D3 sparse graph](#d3-sparse-graph-plotting) (repository root) | The original demo — sparse graph plotting with D3.js. |

## D3 sparse graph plotting

Sparse graph plotting with D3.js, served as a static page.

![result](Assets/result.JPG)

```bash
docker build -t d3demo .
docker run --rm -v "$PWD:/data" -p 8080:8080 d3demo http-server
# then open http://localhost:8080
```

`GraphGen.ipynb` generates `graph.json`; `plot.js` and `index.html` render it.

## Adding a demo

Create a top-level folder, put a `README.md` in it explaining how to run it, and
add a row to the table above. Keep each demo's dependencies inside its own
folder so the demos stay independent.
