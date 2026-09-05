on run
    set resourcesPath to (POSIX path of (path to me)) & "Contents/Resources/"
    try
        do shell script "/bin/sh " & quoted form of (resourcesPath & "launch-wezterm.sh") & " " & quoted form of resourcesPath
    on error errorMessage
        display dialog errorMessage with title "Humming Bird" buttons {"OK"} default button "OK" with icon caution
    end try
end run
