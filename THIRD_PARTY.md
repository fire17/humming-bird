# Third-party software

The web build redistributes the unmodified **Pyodide 314.0.6** runtime under
MPL-2.0. Its corresponding source and license are available from
https://github.com/pyodide/pyodide and https://github.com/pyodide/pyodide/blob/main/LICENSE.
The exact runtime distribution is pinned in `bun.lock`. Pyodide includes CPython
and its standard library under the Python Software Foundation license, accessible
through Python's `license()` function and https://docs.python.org/3/license.html.

The engine bundle includes **pyte 0.8.2** (LGPL-3.0-or-later) and **wcwidth 0.2.13**
(MIT), unmodified from the pinned Python distributions. Source and notices:
https://github.com/selectel/pyte and https://github.com/jquast/wcwidth.
`engine.zip` contains their complete Python source. No changes are made to these
libraries; users may replace their source and rebuild the bundle.

Humming Bird's own code and approved artwork are covered by the repository's MIT
license. Third-party licenses remain their own; the MIT license does not replace them.
