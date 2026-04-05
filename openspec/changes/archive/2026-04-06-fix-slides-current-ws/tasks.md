## 1. Fix the bug

- [x] 1.1 Grep `daemon/__main__.py` for all `SlidesCurrentMsg(` call sites to confirm exact count
- [x] 1.2 Change every non-null broadcast from `SlidesCurrentMsg(**_sc)` to `SlidesCurrentMsg(slides_current=_sc)`

## 2. Verify

- [x] 2.1 Manually confirm that null-clearing calls (`SlidesCurrentMsg(slides_current=None)`) remain unchanged
- [x] 2.2 Run existing daemon tests to check no regressions

## 3. Deploy

- [x] 3.1 Commit and push to master
