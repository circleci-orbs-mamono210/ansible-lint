#!/bin/bash
if [ "$PARAM_MOLECULE_ROLE_TEST" = 1 ]; then
    ansible-galaxy install "git+${CIRCLE_REPOSITORY_URL},${CIRCLE_SHA1}"
fi

if [ "$PARAM_MOLECULE_PLAYBOOK_TEST" = 1 ]; then
    ansible-galaxy install -r roles/requirements.yml
fi

while IFS= read -r -d '' directory
do
    if [[ $directory =~ molecule/.*/requirements.yml ]]; then
        ansible-galaxy install -r "$directory"
    fi
done <  <(find molecule/* -maxdepth 1 -print0)
