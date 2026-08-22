package comskip

import "strconv"

// Settings holds per-job Comskip.ini overrides. Defaults match the bundled template.
type Settings struct {
	DetectBlackFrame        bool `json:"detect_black_frame"`
	DetectLogo              bool `json:"detect_logo"`
	DetectSceneChange       bool `json:"detect_scene_change"`
	DetectFuzzy             bool `json:"detect_fuzzy"`
	DetectClosedCaptions    bool `json:"detect_closed_captions"`
	DetectAspectRatio       bool `json:"detect_aspect_ratio"`
	DetectSilence           bool `json:"detect_silence"`
	DetectCutscenes         bool `json:"detect_cutscenes"`
	Subtitles               bool `json:"subtitles"`
	LogoAtBottom            bool `json:"logo_at_bottom"`
	ConnectBlocksWithLogo   bool `json:"connect_blocks_with_logo"`
	PunishNoLogo            bool `json:"punish_no_logo"`
	AggressiveLogoRejection bool `json:"aggressive_logo_rejection"`
	CutOnARChange           int  `json:"cut_on_ar_change"`
	TickerTape              int  `json:"ticker_tape"`
	ShrinkLogo              int  `json:"shrink_logo"`
	MinCommercialBreak      int  `json:"min_commercialbreak"`
	MaxCommercialBreak      int  `json:"max_commercialbreak"`
	MinCommercialSize       int  `json:"min_commercial_size"`
	MaxCommercialSize       int  `json:"max_commercial_size"`
	MinShowSegmentLength    int  `json:"min_show_segment_length"`
}

const (
	DMBlackFrame        = 1
	DMLogo              = 2
	DMSceneChange       = 4
	DMFuzzy             = 8
	DMClosedCaptions    = 16
	DMAspectRatio       = 32
	DMSilence           = 64
	DMCutscenes         = 128
	DefaultDetectMethod = DMBlackFrame | DMLogo | DMFuzzy | DMAspectRatio // 43
)

// DefaultSettings matches gui/tools/comskip/comskip.ini bundled defaults.
func DefaultSettings() Settings {
	return Settings{
		DetectBlackFrame:        true,
		DetectLogo:              true,
		DetectSceneChange:       false,
		DetectFuzzy:             true,
		DetectClosedCaptions:    false,
		DetectAspectRatio:       true,
		DetectSilence:           false,
		DetectCutscenes:         false,
		Subtitles:               false,
		LogoAtBottom:            false,
		ConnectBlocksWithLogo:   true,
		PunishNoLogo:            true,
		AggressiveLogoRejection: false,
		CutOnARChange:           1,
		TickerTape:              0,
		ShrinkLogo:              5,
		MinCommercialBreak:      25,
		MaxCommercialBreak:      600,
		MinCommercialSize:       4,
		MaxCommercialSize:       125,
		MinShowSegmentLength:    250,
	}
}

func (s Settings) DetectMethod() int {
	v := 0
	if s.DetectBlackFrame {
		v |= DMBlackFrame
	}
	if s.DetectLogo {
		v |= DMLogo
	}
	if s.DetectSceneChange {
		v |= DMSceneChange
	}
	if s.DetectFuzzy {
		v |= DMFuzzy
	}
	if s.DetectClosedCaptions {
		v |= DMClosedCaptions
	}
	if s.DetectAspectRatio {
		v |= DMAspectRatio
	}
	if s.DetectSilence {
		v |= DMSilence
	}
	if s.DetectCutscenes {
		v |= DMCutscenes
	}
	return v
}

func bool01(v bool) string {
	if v {
		return "1"
	}
	return "0"
}

func nonNeg(n int) int {
	if n < 0 {
		return 0
	}
	return n
}

// IniOverrides returns key -> value strings for ini materialization.
func (s Settings) IniOverrides() map[string]string {
	cut := s.CutOnARChange
	if cut < 0 {
		cut = 0
	}
	if cut > 2 {
		cut = 2
	}
	return map[string]string{
		"detect_method":             strconv.Itoa(s.DetectMethod()),
		"subtitles":                 bool01(s.Subtitles),
		"logo_at_bottom":            bool01(s.LogoAtBottom),
		"connect_blocks_with_logo":  bool01(s.ConnectBlocksWithLogo),
		"punish_no_logo":            bool01(s.PunishNoLogo),
		"aggressive_logo_rejection": bool01(s.AggressiveLogoRejection),
		"cut_on_ar_change":          strconv.Itoa(cut),
		"ticker_tape":               strconv.Itoa(nonNeg(s.TickerTape)),
		"shrink_logo":               strconv.Itoa(nonNeg(s.ShrinkLogo)),
		"min_commercialbreak":       strconv.Itoa(nonNeg(s.MinCommercialBreak)),
		"max_commercialbreak":       strconv.Itoa(nonNeg(s.MaxCommercialBreak)),
		"min_commercial_size":       strconv.Itoa(nonNeg(s.MinCommercialSize)),
		"max_commercial_size":       strconv.Itoa(nonNeg(s.MaxCommercialSize)),
		"min_show_segment_length":   strconv.Itoa(nonNeg(s.MinShowSegmentLength)),
	}
}
