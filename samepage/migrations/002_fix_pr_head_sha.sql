-- SamePage schema, version 2: remember which commit of the fix PR was checked and retested.
ALTER TABLE fix_prs ADD COLUMN head_sha TEXT NOT NULL DEFAULT '';
