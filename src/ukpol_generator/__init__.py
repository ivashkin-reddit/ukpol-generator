"""ukpol_generator: generate r/ukpolitics AutoModerator social whitelist rules.

The package is organised as a hexagonal (ports-and-adapters) architecture:

- ``domain``: pure logic with no I/O — models, URL parsing, and rule rendering.
- ``ports``: Protocols describing the seams the application depends on.
- ``adapters``: concrete implementations of the ports (Parliament API, JSON
  file store, YAML output).
- ``application``: use-case services that orchestrate domain logic over ports.
- ``cli``: the driving adapter that wires everything together.
"""
