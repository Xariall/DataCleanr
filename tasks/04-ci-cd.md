# Task: CI/CD — GitHub Actions → Railway

**Priority:** P1
**Status:** In Progress (workflow file created, needs RAILWAY_TOKEN secret)

## What's automated

On every push to `main`:
1. Run `pytest` (all 46 tests)
2. If tests pass → deploy to Railway automatically

## Setup steps

- [x] Create `.github/workflows/deploy.yml`
- [ ] Get Railway token: Railway dashboard → Account Settings → Tokens → New Token
- [ ] Add to GitHub repo secrets: `Settings → Secrets → Actions → New secret`
  - Name: `RAILWAY_TOKEN`
  - Value: (token from Railway)
- [ ] Push to `main` to trigger first automated deploy
- [ ] Verify in Railway dashboard that deploy succeeded

## Done when
A `git push origin main` automatically runs tests and deploys to Railway.
