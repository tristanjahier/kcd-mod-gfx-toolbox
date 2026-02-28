/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 */
class SpiceLedger
{
    var m_Entries;
    var m_TotalWeight;
    var m_SealText;

    function SpiceLedger()
    {
        this.m_Entries = new Array();
        this.m_TotalWeight = 0;
        this.m_SealText = "Open";
    }

    function AddSpice(name, weight, rare)
    {
        var entryName = name;
        if (entryName == undefined || entryName == "") {
            entryName = "Unknown";
        }

        var entryWeight = weight;
        if (entryWeight == undefined || entryWeight < 0) {
            entryWeight = 0;
        }

        var entry = {
            name: entryName,
            weight: entryWeight,
            rare: !!rare
        };

        this.m_Entries.push(entry);
        this.m_TotalWeight = this.m_TotalWeight + entryWeight;
        this.m_SealText = entry.rare ? "Handle with care" : "Open";
        return this.m_Entries.length;
    }

    function RemoveSpice(name)
    {
        var i;

        for (i = 0; i < this.m_Entries.length; i++) {
            if (this.m_Entries[i].name == name) {
                this.m_TotalWeight = this.m_TotalWeight - this.m_Entries[i].weight;
                this.m_Entries.splice(i, 1);
                return true;
            }
        }

        return false;
    }

    function CountRareSpices()
    {
        var i;
        var total = 0;

        for (i = 0; i < this.m_Entries.length; i++) {
            if (this.m_Entries[i].rare) {
                total = total + 1;
            }
        }

        return total;
    }

    function BuildLedgerStamp()
    {
        return this.m_Entries.length + " entries | " + this.m_TotalWeight + " weight | " + this.m_SealText;
    }

    function ResetLedger()
    {
        this.m_Entries = new Array();
        this.m_TotalWeight = 0;
        this.m_SealText = "Open";
    }
}
