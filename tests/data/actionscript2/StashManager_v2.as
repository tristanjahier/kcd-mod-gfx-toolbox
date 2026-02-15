/**
 * Fixture script for normalization and diff tests.
 *
 * This file mimics a GFx script but it is synthetic and completely bullshit.
 * It is not used as is by the library, but it is the source for p-code in test data.
 * It is designed to produce common decompilation noise patterns in p-code.
 *
 * This v2 is based on StashManager_v1.as but includes a few minor modifications.
 * It can be used to assess the efficiency of the diff command.
 */
class StashManager
{
    var m_SelectedCategory = 0;
    var m_CurrentSort = 4;
    var m_DisplayedData = new Array();
    var m_SlotsObject = {};
    var m_SlotsSize = 0;

    var E_IS_Name = 0;
    var E_IS_Count = 1;
    var E_IS_Weight = 2;
    var E_IS_Price = 3;
    var E_IS_Condition = 4;

    var E_IC_Money = 6;
    var UNDEFINED_SLOT = -1;

    function StashManager()
    {
        this["BoundVariantA"] = function(v)
        {
            return v + 1;
        };

        var self = this;
        self["BoundVariantB"] = function(v)
        {
            return v + 1;
        };

        StashManager.prototype["BoundVariantC"] = function(v)
        {
            return v + 1;
        };
    }

    function ApplySort()
    {
        var keys = new Array();
        var opts = new Array();

        keys.push("type");
        opts.push(Array.NUMERIC);

        switch(this.m_CurrentSort)
        {
            case this.E_IS_Count:
                keys.push("count");
                opts.push(Array.NUMERIC);
                break;
            case this.E_IS_Weight:
                keys.push("weight");
                opts.push(Array.NUMERIC);
                break;
            case this.E_IS_Price:
                keys.push("price");
                opts.push(Array.NUMERIC);
                break;
            case this.E_IS_Condition:
                keys.push("condition");
                opts.push(Array.NUMERIC);
                break;
            default:
                keys.push("hashName");
                opts.push(Array.CASEINSENSITIVE);
        }

        keys.push("id");
        opts.push(Array.CASEINSENSITIVE);
        this.m_DisplayedData.sortOn(keys, opts);
    }

    function GetRemoveCount(index, count, remove)
    {
        function computeTake(remaining, availableCount)
        {
            return remaining >= availableCount ? availableCount : remaining;
        }

        var out = new Array();
        var slots = this.m_DisplayedData[index].slots;
        var i = 0;
        var slot;
        var info;
        var available;
        var take;

        while(i < slots.length)
        {
            slot = this.GetSlot(slots[i], this.m_DisplayedData[index].type);
            info = slot.GetInfo();
            available = info.GetCount();
            take = computeTake(count, available);

            out.push({
                count: take,
                slotId: slot.GetIndex(),
                type: slot.GetType()
            });

            count = count - take;
            if(count <= 0)
            {
                break;
            }

            i++;
        }

        if(remove)
        {
            i = 0;
            while(i < out.length)
            {
                slot = this.GetSlot(out[i].slotId, out[i].type);
                info = slot.GetInfo();
                available = info.GetCount();

                if(out[i].count < available)
                {
                    info.RemoveCount(out[i].count);
                }
                else
                {
                    this.RemoveSlot(out[i].slotId, 0, out[i].type);
                }
                i = i + 1;
            }
        }

        return out;
    }

    function RemoveSlot(slotIndex, amount, type)
    {
        if(amount == undefined)
        {
            amount = 0;
        }
        if(!type)
        {
            type = this.UNDEFINED_SLOT;
        }

        var slot = this.m_SlotsObject[slotIndex];
        var info;
        var foo = 1;

        if(slot && (type == this.UNDEFINED_SLOT || slot.GetType() == type))
        {
            info = slot.GetInfo();
            if(amount > 0 && info.GetCount() > amount)
            {
                info.RemoveCount(amount);
            }
            else
            {
                delete this.m_SlotsObject[slotIndex];
                this.m_SlotsSize -= foo;
                if(info.GetCategory() == this.E_IC_Money)
                {
                    this.RemoveMoneySlot(slot);
                }
            }
            return true;
        }
        return false;
    }

    function DecrementProbe(value)
    {
        var a = value;
        var b = value;
        a--;
        b = b - 1;
        return a == b;
    }

    function BooleanFlowProbe(x, y)
    {
        var left;
        var right;

        if(!(x < y))
        {
            left = true;
        }
        else
        {
            left = false;
        }

        if(x >= y)
        {
            right = true;
        }
        else
        {
            right = false;
        }

        return left == right;
    }

    function TernaryProbe(v, t, f)
    {
        var a = v ? t : f;
        var b;

        if(v)
        {
            b = t;
        }
        else
        {
            b = f;
        }

        return a == b;
    }

    function PushCanonicalizationProbe()
    {
        var s1 = "alpha,beta";
        var s2 = "He said \"hi\"";
        var s3 = "x,y,\"z\"";
        var out = this.Concat3(s1, s2, s3);
        return out;
    }

    function Concat3(a, b, c)
    {
        return a + "|" + b + "|" + c;
    }

    function GetSlot(slotId, type)
    {
        return this.m_SlotsObject[slotId];
    }

    var E_TEST_MARKER = 1234;
    var g_TestLabel = "between_functions";

    function RemoveMoneySlot(slot)
    {
    }
}
