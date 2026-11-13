# desk-idle: puts Alex's desk to sleep (arm rested and released, desk light and projector off)
# once nothing has used it for an hour. monitor.py decides from fixed rules; the cron model runs
# only when its verdict changes, and then only checks the overhead photo for a person before
# running the exact SLEEP lines the script printed. The job needs terminal and vision (Alex's
# explicit OK for this job); its toolsets are set on the job itself.
{
  aiBox.hermesCron.desk-idle = {
    schedule = "30 * * * *";
    monitorScript = ./monitor.py;
    prompt = ''
      The output above is desk-idle's verdict, computed by a script from fixed rules. Do not
      second-guess it and do not run any check of your own.
      - VERDICT: ASLEEP or VERDICT: IN_USE ... -> answer exactly [SILENT].
      - VERDICT: CHECK_PHOTO <image> -> look at <image> with the vision tool and ask: "Is a
        person, a hand or a human arm visible? The robot arm, cameras, blocks and paper are always
        there." If yes or unsure, answer exactly [SILENT]. If no, run each SLEEP: line of the
        output with the terminal, exactly as written, then answer with one short line for Alex
        saying what is now off, quoting any error, and nothing you did not run.
    '';
  };
}
