# board-keeper: keeps Alex's in-flight work from being forgotten (Alex, 11-18: "I worry that there
# are loose threads I'm forgetting about, and only because I ask about them do they get picked back
# up ... Maybe just set up a cron job to check it ... can't we use existing tooling?").
# monitor.py snapshots the kanban board, the lab lock and queue, the open PRs and the running agent
# jobs; the agent runs at most every two hours, or when the snapshot changes. It nudges stuck work
# with the tools that exist (kanban comments and unblocks, a message to a job) and messages Alex
# only when a card needs him. The job needs a terminal (Alex's explicit OK for this job, 11-18) and
# no web; its toolsets are set on the job.
{
  aiBox.hermesCron.board-keeper = {
    schedule = "every 30m";
    monitorScript = ./monitor.py;
    prompt = ''
      The text above is board-keeper's snapshot of Hermes's open work for Alex: kanban cards,
      the lab lock and queue (~/workspace/lab-stretch.queue), open pull requests, and the
      running agent jobs (`agent list`, `agent peek <job> 60`; a `coder` card runs as the job
      `card-<id>`). IDLE: answer exactly [SILENT]. If a line says `unreadable: ...`, report
      that to Alex in one line and stop.

      Find work that is stuck or forgotten, and get it moving again:
      - A blocked card whose blocker is gone (`hermes kanban show <id>` gives the reason; e.g.
        the lab it waited for is free, the PR it waited for merged): comment what changed, then
        `hermes kanban unblock <id>`; a `coder` card's job carries on with that context.
      - The lab is free (lab-stretch status says free) and the queue names a job: tell that
        job, with `agent send <job> "..."`, it may take the lab now (`lab-stretch acquire
        <name>`).
      - A job outside the board (not `card-<id>`) that has been idle for over an hour with its
        work unfinished, and isn't waiting for Alex: ask it, with `agent send`, what it needs
        to finish, and to carry on.
      - An open PR with no card: create one naming it (`hermes kanban create`), unassigned.
      Comment on each card you act on (`hermes kanban comment <id> "board-keeper: ..."`).

      Never merge, push, approve, switch the system, move the arm, or stop a job. Never
      decide anything for Alex.

      Answer for Alex only with what needs him: a decision he owes, a PR that's ready for him
      to try or approve (say what it is in plain words plus its full URL, never just a
      number), or a block only he can lift. Report an item only when it's new in this run's
      diff from the last snapshot (an earlier run already told him about the rest). Name each
      item once, in a short line. If nothing needs him (including when you only nudged work),
      answer exactly [SILENT].
    '';
  };
}
