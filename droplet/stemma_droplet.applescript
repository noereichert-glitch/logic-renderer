-- Stemma droplet
-- Drag sessions onto it  -> plants an ALIAS in the stemma folder (original never moves).
--                           Dropped Finder aliases are resolved to their originals first.
-- Double-click it        -> opens the stemma folder in Finder.
-- Nothing here ever triggers a render.

property stemmaFolderRaw : "~/Music/Stemma"

on resolvedFolder()
	return do shell script "echo " & stemmaFolderRaw
end resolvedFolder

on open theItems
	set folderPath to my resolvedFolder()
	do shell script "mkdir -p " & quoted form of (folderPath & "/Renders")
	repeat with anItem in theItems
		set p to ""
		try
			tell application "Finder"
				if class of item anItem is alias file then
					set p to POSIX path of ((original item of item anItem) as alias)
				else
					set p to POSIX path of anItem
				end if
			end tell
		on error
			set p to POSIX path of anItem
		end try
		if p ends with "/" then set p to text 1 thru -2 of p
		set nm to do shell script "basename " & quoted form of p
		if nm ends with ".logicx" or nm ends with ".als" then
			try
				-- ln -s without -f: an existing alias of the same name is left alone
				do shell script "ln -s " & quoted form of p & " " & quoted form of (folderPath & "/" & nm)
			end try
		end if
	end repeat
end open

on run
	set folderPath to my resolvedFolder()
	do shell script "mkdir -p " & quoted form of (folderPath & "/Renders")
	tell application "Finder"
		open (POSIX file folderPath as alias)
		activate
	end tell
end run
