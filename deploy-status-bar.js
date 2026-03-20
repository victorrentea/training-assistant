// deploy-status-bar.js — macOS menu bar status item for deploy countdown
// Run with: osascript -l JavaScript deploy-status-bar.js
//
// Communication: reads /tmp/deploy_status.txt every 0.5s
// - Non-empty content → displayed as menu bar title
// - Empty or missing file → title set to empty string (hidden)

ObjC.import('Cocoa');

var statusItem = null;
var statusFile = '/tmp/deploy_status.txt';

function setup() {
  var bar = $.NSStatusBar.systemStatusBar;
  statusItem = bar.statusItemWithLength($.NSVariableStatusItemLength);
  statusItem.button.font = $.NSFont.monospacedSystemFontOfSize_weight(12, $.NSFontWeightMedium);
  statusItem.button.title = $('');
}

function readStatusFile() {
  var fm = $.NSFileManager.defaultManager;
  if (!fm.fileExistsAtPath(statusFile)) {
    return '';
  }
  var data = $.NSString.stringWithContentsOfFileEncodingError(statusFile, $.NSUTF8StringEncoding, null);
  if (data.isNil()) {
    return '';
  }
  return ObjC.unwrap(data).trim();
}

function update() {
  var text = readStatusFile();
  statusItem.button.title = $(text);
}

setup();

// Run loop that polls every 0.5s
var interval = 0.5;
while (true) {
  update();
  $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(interval));
}
