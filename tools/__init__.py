"""Developer tools, run as files: python tools/<name>.py.

Nothing imports this package. The file is here for coverage: with
`source = .`, coverage looks for files nothing imported only in
directories that are packages, so without it a new, untested tool here
would be missing from the report rather than shown at 0% -- and the 100%
gate would pass over it.
"""
