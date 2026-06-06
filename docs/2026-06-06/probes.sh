#!/bin/bash
# Reusable Logic Pro UI discovery probes (element-level System Events only).
# Run individual sections as needed. PROC is the discovered process name.
# Usage: bash probes.sh <section>   e.g.  bash probes.sh dialog
PROC="Logic Pro X"
set -e

case "${1:-help}" in

procname)  # discover the real process / executable name
  echo "-- background-only=false processes (look for Logic) --"
  osascript -e 'tell application "System Events" to get name of every process whose background only is false' | tr ',' '\n' | grep -i logic
  echo "-- pgrep -x exact match --"
  pgrep -x "Logic Pro X" || echo "(no 'Logic Pro X')"
  pgrep -x "Logic Pro"   || echo "(no 'Logic Pro')"
  ;;

windows)  # current windows + sheets (readiness signal)
  osascript -e "tell application \"System Events\" to tell process \"$PROC\"
    set out to \"count: \" & (count of windows) & return
    repeat with w in windows
      set out to out & \"win [\" & (name of w) & \"] role=\" & (role of w) & \" sheets=\" & (count of sheets of w) & return
    end repeat
    return out
  end tell"
  ;;

menu)  # File > Export submenu item titles
  osascript -e "tell application \"System Events\" to tell process \"$PROC\" to return name of every menu item of menu \"Export\" of menu item \"Export\" of menu \"File\" of menu bar 1"
  ;;

trigger)  # bring frontmost and open the export dialog
  osascript -e "tell application \"System Events\" to tell process \"$PROC\"
    set frontmost to true
    delay 0.5
    click menu item \"All Tracks as Audio Files…\" of menu \"Export\" of menu item \"Export\" of menu \"File\" of menu bar 1
  end tell"
  ;;

dialog)  # dump interactive controls of the export dialog (window "Open")
  osascript -e "tell application \"System Events\" to tell process \"$PROC\"
    set out to \"\"
    repeat with e in (entire contents of window \"Open\")
      try
        set r to role of e
        if r is in {\"AXCheckBox\",\"AXPopUpButton\",\"AXButton\",\"AXTextField\",\"AXRadioButton\"} then
          set nm to \"\"
          try
            set nm to name of e
          end try
          set vl to \"\"
          try
            set vl to (value of e) as text
          end try
          set out to out & r & \" | name=[\" & nm & \"] | val=[\" & vl & \"]\" & return
        end if
      end try
    end repeat
    return out
  end tell"
  ;;

popups)  # value + (opened) menu items of each pop up button in the dialog
  for i in 1 2 3 4 5 6; do
    echo "-- pop up button $i --"
    osascript -e "tell application \"System Events\" to tell process \"$PROC\"
      if not (exists window \"Open\") then return \"NO DIALOG\"
      set v to (value of pop up button $i of window \"Open\") as text
      click pop up button $i of window \"Open\"
      delay 0.5
      set m to name of every menu item of menu 1 of pop up button $i of window \"Open\"
      key code 53
      return \"val=[\" & v & \"] menu=\" & (m as text)
    end tell" || true
  done
  ;;

cancel)  # dismiss the dialog without exporting
  osascript -e "tell application \"System Events\" to tell process \"$PROC\"
    if exists button \"Cancel\" of window \"Open\" then click button \"Cancel\" of window \"Open\"
  end tell"
  ;;

*)
  echo "sections: procname windows menu trigger dialog popups cancel"
  ;;
esac
