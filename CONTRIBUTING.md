# Contributing

This project is not currently accepting external contributions, but we're
actively working toward opening this up. We value community input and look
forward to collaborating in the future. For now, feel free to fork and
experiment!

Most contributions require you to agree to a Contributor License Agreement
(CLA) declaring that you have the right to, and actually do, grant us the
rights to use your contribution. For details, visit
[Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine
whether you need to provide a CLA and decorate the PR appropriately (e.g.,
status check, comment). Simply follow the instructions provided by the bot.
You will only need to do this once across all repos using our CLA.

This project has adopted the
[Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the
[Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/)
or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any
additional questions or comments.

## Maintainer note: branch protection

`main` protection is defined in
[`.github/branch-protection-ruleset.json`](.github/branch-protection-ruleset.json).
Apply it with repo-admin rights:

```bash
gh api -X POST repos/microsoft/amplifier-work-tracker/rulesets \
  --input .github/branch-protection-ruleset.json
```

It deliberately sets `required_approving_review_count: 0` rather than
1-with-a-bypass. Bypass actors bypass the *entire* ruleset including
required status checks, so a bypass would also exempt the bypasser from CI.
With 0, the gate -- PR required, CI green, linear history, no force-push --
applies to everyone including maintainers, and a solo maintainer can still
merge their own PR without admin rights. Raise the count to 1 when a second
maintainer exists.
