//go:build !windows

package winffmpeg

// ConsoleGuard selects title/menu text for a protected child console.
type ConsoleGuard struct {
	ToolLabel string
	MenuText  string
}

var (
	// GuardFFmpeg labels FFmpeg recording consoles.
	GuardFFmpeg = ConsoleGuard{
		ToolLabel: "FFmpeg",
		MenuText:  "Close disabled while FFmpeg is recording",
	}
	// GuardCCExtractor labels live CCExtractor worker consoles.
	GuardCCExtractor = ConsoleGuard{
		ToolLabel: "CCExtractor",
		MenuText:  "Close disabled while CCExtractor is extracting captions",
	}
)

// ArmConsoleCloseGuard is a no-op on non-Windows platforms.
func ArmConsoleCloseGuard(_ int, _ ConsoleGuard) {}
