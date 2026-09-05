class HummingBird < Formula
  include Language::Python::Virtualenv

  desc "Living neon hummingbird garden in your terminal"
  homepage "https://github.com/fire17/humming-bird"
  url "https://github.com/fire17/humming-bird/archive/refs/tags/v1.1.0.tar.gz"
  sha256 "00eb1b5696e30f318345976f9bc8544d3a7769d238eaac0ac0e6871633b18507"
  license "MIT"

  depends_on "python@3.12"

  resource "pyte" do
    url "https://files.pythonhosted.org/packages/ab/ab/b599762933eba04de7dc5b31ae083112a6c9a9db15b01d3109ad797559d9/pyte-0.8.2.tar.gz"
    sha256 "5af970e843fa96a97149d64e170c984721f20e52227a2f57f0a54207f08f083f"
  end

  resource "wcwidth" do
    url "https://files.pythonhosted.org/packages/6c/63/53559446a878410fc5a5974feb13d31d78d752eb18aeba59c7fef1af7598/wcwidth-0.2.13.tar.gz"
    sha256 "72ea0c06399eb286d978fdedb6923a9eb47e1c486ce63e9b4e64fc18303972b5"
  end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Run humming-bird in a real truecolor terminal.
      Screensaver: press o. Pilot mode: p. Exit: q.
      Preferences live in ~/.config/hummingbird-tui/settings.json.
      Uninstall: brew uninstall humming-bird (preferences are kept).
    EOS
  end

  test do
    ENV["XDG_CONFIG_HOME"] = testpath.to_s
    assert_match "Humming Bird 1.1.0", shell_output("#{bin}/humming-bird --version")
    assert_match "60 verified wing frames", shell_output("#{bin}/humming-bird --check")
  end
end
