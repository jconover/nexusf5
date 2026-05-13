"""Mock-f5 response fixtures for endpoints the brownfield-extractor walks.

Each fixture module documents its upstream citation in the module docstring
(clouddocs URL or ACC source path + commit hash, plus access date). Per
ADR 007 §Testing strategy, fixtures are the contract real F5 supplies; the
mock returning anything else trains the extractor on shapes that fail in
production. New fixtures must carry the same citation discipline.
"""
