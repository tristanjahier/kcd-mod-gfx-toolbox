/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 */

var doIKnowWhatIDo = false;
var g_GameMode = "normal";
var g_SelectedQuest = "";
var g_QuestCount = 0;
var g_ShowHints = true;

function SetGameMode(mode)
{
    g_GameMode = mode;
}

function SelectQuest(name)
{
    g_SelectedQuest = name;
    if (name != "") {
        g_QuestCount = g_QuestCount + 1;
    }
}

function ToggleHints()
{
    g_ShowHints = !g_ShowHints;
}

function BuildHudBanner(playerName, health, stamina)
{
    var hints = g_ShowHints ? "Hints ON" : "Hints OFF";
    return playerName + " | HP " + health + " | STA " + stamina + " | " + hints + " | mode:" + g_GameMode;
}

function ShouldWarnLowStamina(stamina)
{
    if (g_GameMode == "hard" && stamina < 30) {
        return true;
    }

    if (stamina < 15) {
        return true;
    }

    return false;
}
