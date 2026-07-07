package comskip

import (
	"fmt"
	"os"
	"strings"
)

func escapeFFMeta(value string) string {
	replacer := strings.NewReplacer(
		`\`, `\\`,
		`=`, `\=`,
		`;`, `\;`,
		`#`, `\#`,
		"\n", `\n`,
	)
	return replacer.Replace(value)
}

func ms(sec float64) int {
	if sec < 0 {
		return 0
	}
	return int(sec*1000 + 0.5)
}

// WriteChaptersFFMeta writes episode and commercial chapter metadata.
func WriteChaptersFFMeta(path, title string, episodes []EpisodeSegment, commercials []CommercialBreak, totalSec float64) error {
	var b strings.Builder
	b.WriteString(";FFMETADATA1\n")
	b.WriteString(fmt.Sprintf("title=%s\n", escapeFFMeta(title)))
	for _, ep := range episodes {
		end := ep.EndSec
		if end <= 0 {
			end = totalSec
		}
		b.WriteString("\n[CHAPTER]\n")
		b.WriteString("TIMEBASE=1/1000\n")
		b.WriteString(fmt.Sprintf("START=%d\n", ms(ep.StartSec)))
		b.WriteString(fmt.Sprintf("END=%d\n", ms(end)))
		b.WriteString(fmt.Sprintf("title=Episode %d\n", ep.Index))
	}
	for _, br := range commercials {
		label := "Commercial"
		if br.EpisodeIndex > 0 {
			label = fmt.Sprintf("Commercial (Ep %d)", br.EpisodeIndex)
		}
		b.WriteString("\n[CHAPTER]\n")
		b.WriteString("TIMEBASE=1/1000\n")
		b.WriteString(fmt.Sprintf("START=%d\n", ms(br.StartSec)))
		b.WriteString(fmt.Sprintf("END=%d\n", ms(br.EndSec)))
		b.WriteString(fmt.Sprintf("title=%s\n", escapeFFMeta(label)))
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}
