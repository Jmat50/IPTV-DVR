package comskip

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var iniKeyLine = regexp.MustCompile(`^([A-Za-z0-9_]+)=(.*)$`)

// ApplyIniOverrides replaces first occurrence of each key; appends missing keys.
func ApplyIniOverrides(templateText string, overrides map[string]string) string {
	remaining := make(map[string]string, len(overrides))
	for k, v := range overrides {
		remaining[k] = v
	}
	lines := strings.SplitAfter(templateText, "\n")
	out := make([]string, 0, len(lines)+len(overrides)+2)
	for _, raw := range lines {
		line := strings.TrimRight(raw, "\r\n")
		newline := ""
		if strings.HasSuffix(raw, "\r\n") {
			newline = "\r\n"
		} else if strings.HasSuffix(raw, "\n") {
			newline = "\n"
		}
		code := line
		comment := ""
		hasComment := false
		if i := strings.Index(line, ";"); i >= 0 {
			code = line[:i]
			comment = line[i+1:]
			hasComment = true
		}
		m := iniKeyLine.FindStringSubmatch(strings.TrimRight(code, " \t"))
		if m != nil {
			key := m[1]
			if val, ok := remaining[key]; ok {
				delete(remaining, key)
				if hasComment {
					out = append(out, key+"="+val+"\t\t;"+comment+newline)
				} else {
					out = append(out, key+"="+val+newline)
				}
				continue
			}
		}
		if newline == "" && raw != "" {
			out = append(out, raw+"\n")
		} else {
			out = append(out, raw)
		}
	}
	if len(remaining) > 0 {
		if len(out) > 0 && !strings.HasSuffix(out[len(out)-1], "\n") {
			out[len(out)-1] = out[len(out)-1] + "\n"
		}
		out = append(out, "\n; Per-job overrides (appended)\n")
		// Stable-ish order not required; map iteration is fine for tests that check presence
		for key, val := range remaining {
			out = append(out, key+"="+val+"\n")
		}
	}
	return strings.Join(out, "")
}

// MaterializeIni writes template+settings to destPath and returns destPath.
func MaterializeIni(settings Settings, destPath, templatePath string) (string, error) {
	tpl := templatePath
	if tpl == "" {
		tpl = ResolveIni("")
	}
	data, err := os.ReadFile(tpl)
	if err != nil {
		return "", err
	}
	merged := ApplyIniOverrides(string(data), settings.IniOverrides())
	if err := os.MkdirAll(filepath.Dir(destPath), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(destPath, []byte(merged), 0o644); err != nil {
		return "", err
	}
	return destPath, nil
}
