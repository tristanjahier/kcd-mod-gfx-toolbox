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
    var questInfo = g_SelectedQuest == "" ? "No quest" : g_SelectedQuest;
    return playerName + " | HP " + health + " | STA " + stamina + " | " + hints + " | mode:" + g_GameMode + " | quest:" + questInfo;
}

function ShouldWarnLowStamina(stamina)
{
    if (g_GameMode == "hard" && stamina < 35) {
        return true;
    }

    if (g_GameMode == "normal" && stamina < 20) {
        return true;
    }

    return false;
}

function GetHintStateLabel()
{
    return g_ShowHints ? "Hints ON" : "Hints OFF";
}
