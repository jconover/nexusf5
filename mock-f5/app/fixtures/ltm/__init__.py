"""LTM (Local Traffic Manager) iControl REST GET response fixtures.

Each module returns a representative response body for one LTM endpoint
family. The brownfield-extractor (per ADR 007) walks these endpoints to
construct AS3 declarations from existing device state. Shapes match the
documented F5 iControl REST contract; provenance lives in each module's
docstring.
"""
